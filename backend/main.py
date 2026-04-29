from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiofiles
import anthropic
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from sse_starlette.sse import EventSourceResponse

from backend.models import ChapterSession
from backend.storage import (
    save_session,
    load_session,
    save_chapter_text,
    session_exists,
    delete_session,
    list_sessions,
)
from backend.agent import BookEditorAgent

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "5")) * 1024 * 1024
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "100"))

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _require_valid_session_id(session_id: str) -> None:
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID.")


def _safe_filename(raw: str | None) -> str:
    name = raw or "chapter.txt"
    name = Path(name).name  # strip any directory components
    name = re.sub(r"[^\w\s.\-]", "_", name)[:120]
    return name or "chapter.txt"


# ── Per-session in-memory state ───────────────────────────────────────────────
_queues: dict[str, asyncio.Queue] = {}
_tasks: dict[str, asyncio.Task] = {}
_last_pending: dict[str, dict] = {}


def _cleanup_session_state(session_id: str) -> None:
    _queues.pop(session_id, None)
    _last_pending.pop(session_id, None)
    _tasks.pop(session_id, None)


# ── App lifecycle ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Graceful shutdown: cancel all running agent tasks
    for sid, task in list(_tasks.items()):
        if not task.done():
            log.info("Cancelling agent task for session %s", sid)
            task.cancel()
    await asyncio.gather(*[t for t in _tasks.values() if not t.done()], return_exceptions=True)


app = FastAPI(title="Book Chapter Editor", version="1.0.0", lifespan=lifespan)

# CORS — restrict to same origin by default; override via CORS_ORIGINS env var
_cors_origins = os.environ.get("CORS_ORIGINS", "").split(",") if os.environ.get("CORS_ORIGINS") else []
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
        "style-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
        "connect-src 'self';"
    )
    return response


# ── Anthropic client ──────────────────────────────────────────────────────────
def _get_client() -> anthropic.AsyncAnthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    timeout = float(os.environ.get("ANTHROPIC_TIMEOUT", "120"))

    if not api_key:
        token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
        if token_file:
            p = Path(token_file)
            if p.exists():
                api_key = p.read_text(encoding="utf-8").strip()[:4096]

    if not api_key:
        raise HTTPException(status_code=500, detail="No API key found. Set ANTHROPIC_API_KEY.")

    kwargs: dict = {"base_url": base_url, "timeout": timeout}
    if api_key.startswith("sk-ant-si"):
        kwargs["auth_token"] = api_key
    else:
        kwargs["api_key"] = api_key
    return anthropic.AsyncAnthropic(**kwargs)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(list_sessions())}


@app.post("/sessions")
async def create_session(file: UploadFile = File(...)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit.")

    if len(list_sessions()) >= MAX_SESSIONS:
        raise HTTPException(status_code=429, detail="Session limit reached. Delete old sessions first.")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File must be UTF-8 or Latin-1 encoded text.")

    if not text.strip():
        raise HTTPException(status_code=400, detail="File is empty.")

    session = ChapterSession(
        filename=_safe_filename(file.filename),
        original_text=text,
        current_text=text,
    )
    save_session(session)
    save_chapter_text(session.session_id, text)
    log.info("Created session %s for file %r", session.session_id, session.filename)
    return {"session_id": session.session_id, "filename": session.filename, "status": session.status}


@app.get("/sessions")
async def get_sessions():
    return list_sessions()


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    _require_valid_session_id(session_id)
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return load_session(session_id).model_dump()


@app.post("/sessions/{session_id}/start")
async def start_session(session_id: str):
    _require_valid_session_id(session_id)
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    if session_id in _tasks and not _tasks[session_id].done():
        raise HTTPException(status_code=409, detail="Session already running.")

    session = load_session(session_id)
    if session.status == "complete":
        raise HTTPException(status_code=409, detail="Session already complete.")

    queue: asyncio.Queue = asyncio.Queue()
    _queues[session_id] = queue
    agent = BookEditorAgent(_get_client())

    async def _run():
        try:
            async for event in agent.run_session(session, queue):
                if event["event"] == "change":
                    _last_pending[session_id] = event
                elif event["event"] in ("decision", "pass_complete", "complete"):
                    _last_pending.pop(session_id, None)
        except Exception as exc:
            log.exception("Agent task failed for session %s: %s", session_id, exc)
        finally:
            _tasks.pop(session_id, None)

    _tasks[session_id] = asyncio.create_task(_run())
    return {"ok": True, "message": "Agent started."}


@app.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str):
    _require_valid_session_id(session_id)
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    agent = BookEditorAgent(_get_client())

    async def _generator():
        session = load_session(session_id)

        # Replay last unanswered change on reconnect
        if session_id in _tasks and not _tasks[session_id].done():
            pending = _last_pending.get(session_id)
            if pending:
                yield {"event": pending["event"], "data": json.dumps(pending["data"])}

        if session_id not in _tasks or _tasks[session_id].done():
            if session.status in ("uploaded", "analyzing", "pass1", "pass2", "pass3", "audit"):
                queue: asyncio.Queue = asyncio.Queue()
                _queues[session_id] = queue
                try:
                    async for event in agent.run_session(session, queue):
                        if event["event"] == "change":
                            _last_pending[session_id] = event
                        elif event["event"] in ("decision", "pass_complete", "complete"):
                            _last_pending.pop(session_id, None)
                        yield {"event": event["event"], "data": json.dumps(event["data"])}
                finally:
                    _queues.pop(session_id, None)
                return

            if session.status == "complete":
                yield {"event": "complete", "data": json.dumps({"final_text": session.current_text, "stats": {}})}
                return

        prev_queue = _queues.get(session_id)
        if prev_queue is None:
            yield {"event": "error", "data": json.dumps({"message": "No active session queue."})}
            return

        bridge: asyncio.Queue = asyncio.Queue()

        async def _relay():
            try:
                session_reload = load_session(session_id)
                async for event in agent.run_session(session_reload, prev_queue):
                    await bridge.put(event)
            finally:
                await bridge.put(None)

        relay_task = asyncio.create_task(_relay())
        try:
            while True:
                event = await bridge.get()
                if event is None:
                    break
                yield {"event": event["event"], "data": json.dumps(event["data"])}
        finally:
            relay_task.cancel()

    return EventSourceResponse(_generator())


class DecisionRequest(BaseModel):
    change_id: str
    status: str

    @field_validator("change_id")
    @classmethod
    def validate_change_id(cls, v: str) -> str:
        if not _UUID_RE.match(v):
            raise ValueError("change_id must be a valid UUID")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("accepted", "rejected"):
            raise ValueError("status must be 'accepted' or 'rejected'")
        return v


@app.post("/sessions/{session_id}/decision")
async def submit_decision(session_id: str, req: DecisionRequest):
    _require_valid_session_id(session_id)
    queue = _queues.get(session_id)
    if queue is None:
        raise HTTPException(status_code=409, detail="No active agent for this session.")
    await queue.put({"change_id": req.change_id, "status": req.status})
    return {"ok": True}


@app.post("/sessions/{session_id}/skip_pass")
async def skip_pass(session_id: str):
    _require_valid_session_id(session_id)
    queue = _queues.get(session_id)
    if queue is None:
        raise HTTPException(status_code=409, detail="No active agent for this session.")
    session = load_session(session_id)
    if session.last_pending_change_id:
        await queue.put({"change_id": session.last_pending_change_id, "status": "rejected"})
    return {"ok": True}


@app.get("/sessions/{session_id}/download")
async def download_session(session_id: str):
    _require_valid_session_id(session_id)
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    session = load_session(session_id)
    content = session.current_text.encode("utf-8")
    stem = Path(session.filename).stem
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}_edited.txt"'},
    )


@app.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    _require_valid_session_id(session_id)
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    task = _tasks.get(session_id)
    if task and not task.done():
        task.cancel()
    _cleanup_session_state(session_id)
    delete_session(session_id)
    log.info("Deleted session %s", session_id)
    return {"ok": True}


# ── Static frontend ───────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
