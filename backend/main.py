from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.models import ChapterSession
from backend.storage import (
    save_session,
    load_session,
    save_chapter_text,
    load_chapter_text,
    session_exists,
    delete_session,
    list_sessions,
)
from backend.agent import BookEditorAgent

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Book Chapter Editor", version="1.0.0")

# Per-session state
_queues: dict[str, asyncio.Queue] = {}
_tasks: dict[str, asyncio.Task] = {}
_last_pending: dict[str, dict] = {}  # session_id → last unanswered change event


def _get_client() -> anthropic.AsyncAnthropic:
    # Try standard API key first
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    # Fall back to Claude Code session token (OAuth bearer token format)
    if not api_key:
        token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
        if token_file and Path(token_file).exists():
            api_key = Path(token_file).read_text().strip()

    if not api_key:
        raise HTTPException(status_code=500, detail="No API key found. Set ANTHROPIC_API_KEY.")

    # OAuth/session tokens (sk-ant-si-*) use auth_token (Authorization: Bearer)
    if api_key.startswith("sk-ant-si"):
        return anthropic.AsyncAnthropic(auth_token=api_key, base_url=base_url)
    return anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.post("/sessions")
async def create_session(file: UploadFile = File(...)):
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    session = ChapterSession(
        filename=file.filename or "chapter.txt",
        original_text=text,
        current_text=text,
    )
    save_session(session)
    save_chapter_text(session.session_id, text)
    return {"session_id": session.session_id, "filename": session.filename, "status": session.status}


@app.get("/sessions")
async def get_sessions():
    return list_sessions()


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    session = load_session(session_id)
    return session.model_dump()


@app.post("/sessions/{session_id}/start")
async def start_session(session_id: str):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    if session_id in _tasks and not _tasks[session_id].done():
        raise HTTPException(status_code=409, detail="Session already running.")

    session = load_session(session_id)
    if session.status == "complete":
        raise HTTPException(status_code=409, detail="Session already complete.")

    queue: asyncio.Queue = asyncio.Queue()
    _queues[session_id] = queue

    client = _get_client()
    agent = BookEditorAgent(client)

    async def _run():
        async for event in agent.run_session(session, queue):
            if event["event"] == "change":
                _last_pending[session_id] = event
            elif event["event"] in ("decision", "pass_complete", "complete"):
                _last_pending.pop(session_id, None)

    task = asyncio.create_task(_run())
    _tasks[session_id] = task
    return {"ok": True, "message": "Agent started."}


@app.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    client = _get_client()
    agent = BookEditorAgent(client)

    async def _generator():
        session = load_session(session_id)

        # If agent task is running, yield the last pending change on reconnect
        if session_id in _tasks and not _tasks[session_id].done():
            pending = _last_pending.get(session_id)
            if pending:
                yield {"event": pending["event"], "data": json.dumps(pending["data"])}

        # If no task is running yet, start a fresh one
        if session_id not in _tasks or _tasks[session_id].done():
            if session.status in ("uploaded", "analyzing", "pass1", "pass2", "pass3", "audit"):
                queue: asyncio.Queue = asyncio.Queue()
                _queues[session_id] = queue

                # Stream directly through SSE
                async for event in agent.run_session(session, queue):
                    if event["event"] == "change":
                        _last_pending[session_id] = event
                    elif event["event"] in ("decision", "pass_complete", "complete"):
                        _last_pending.pop(session_id, None)
                    yield {"event": event["event"], "data": json.dumps(event["data"])}
                return

            if session.status == "complete":
                yield {"event": "complete", "data": json.dumps({"final_text": session.current_text, "stats": {}})}
                return

        # Task is running; stay alive to forward future events
        # (primary path: user opened stream after /start)
        prev_queue = _queues.get(session_id)
        if prev_queue is None:
            yield {"event": "error", "data": json.dumps({"message": "No active session queue."})}
            return

        # Relay events from the background task via a bridge queue
        bridge: asyncio.Queue = asyncio.Queue()

        async def _run_and_relay():
            session_reload = load_session(session_id)
            async for event in agent.run_session(session_reload, prev_queue):
                await bridge.put(event)
            await bridge.put(None)  # sentinel

        relay_task = asyncio.create_task(_run_and_relay())
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
    status: str  # "accepted" or "rejected"


@app.post("/sessions/{session_id}/decision")
async def submit_decision(session_id: str, req: DecisionRequest):
    if req.status not in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'accepted' or 'rejected'.")
    queue = _queues.get(session_id)
    if queue is None:
        raise HTTPException(status_code=409, detail="No active agent for this session.")
    await queue.put({"change_id": req.change_id, "status": req.status})
    return {"ok": True}


@app.post("/sessions/{session_id}/skip_pass")
async def skip_pass(session_id: str):
    """Bulk-reject all remaining pending changes in the current pass."""
    queue = _queues.get(session_id)
    if queue is None:
        raise HTTPException(status_code=409, detail="No active agent for this session.")
    session = load_session(session_id)
    if session.last_pending_change_id:
        await queue.put({"change_id": session.last_pending_change_id, "status": "rejected"})
    return {"ok": True}


@app.get("/sessions/{session_id}/download")
async def download_session(session_id: str):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    session = load_session(session_id)
    text_path = UPLOAD_DIR / f"{session_id}.txt"
    # Write final text to disk for download
    text_path.write_text(session.current_text, encoding="utf-8")
    stem = Path(session.filename).stem
    return FileResponse(
        path=str(text_path),
        media_type="text/plain",
        filename=f"{stem}_edited.txt",
    )


@app.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    task = _tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    _queues.pop(session_id, None)
    _last_pending.pop(session_id, None)
    delete_session(session_id)
    return {"ok": True}


# ── Static frontend ───────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
