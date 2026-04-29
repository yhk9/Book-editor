from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from backend.models import ChapterSession

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

log = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _validate_session_id(session_id: str) -> None:
    if not _UUID_RE.match(session_id):
        raise ValueError(f"Invalid session_id format: {session_id!r}")


def _session_path(session_id: str) -> Path:
    _validate_session_id(session_id)
    return UPLOAD_DIR / f"{session_id}.json"


def _text_path(session_id: str) -> Path:
    _validate_session_id(session_id)
    return UPLOAD_DIR / f"{session_id}.txt"


def save_session(session: ChapterSession) -> None:
    tmp = _session_path(session.session_id).with_suffix(".tmp")
    tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(_session_path(session.session_id))


def load_session(session_id: str) -> ChapterSession:
    data = _session_path(session_id).read_text(encoding="utf-8")
    return ChapterSession.model_validate_json(data)


def save_chapter_text(session_id: str, text: str) -> None:
    tmp = _text_path(session_id).with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(_text_path(session_id))


def load_chapter_text(session_id: str) -> str:
    return _text_path(session_id).read_text(encoding="utf-8")


def session_exists(session_id: str) -> bool:
    return _session_path(session_id).exists()


def delete_session(session_id: str) -> None:
    for p in [_session_path(session_id), _text_path(session_id)]:
        if p.exists():
            p.unlink()


def list_sessions() -> list[dict]:
    results = []
    for p in sorted(UPLOAD_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            session = ChapterSession.model_validate_json(p.read_text(encoding="utf-8"))
            results.append({
                "session_id": session.session_id,
                "filename": session.filename,
                "status": session.status,
            })
        except Exception as exc:
            log.warning("Skipping corrupt session file %s: %s", p, exc)
            continue
    return results
