from __future__ import annotations
import json
from pathlib import Path
from backend.models import ChapterSession

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def _session_path(session_id: str) -> Path:
    return UPLOAD_DIR / f"{session_id}.json"


def _text_path(session_id: str) -> Path:
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
        except Exception:
            continue
    return results
