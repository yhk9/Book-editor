from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
import uuid


class VoiceFingerprint(BaseModel):
    avg_sentence_length: float = 0.0
    short_sentence_ratio: float = 0.0      # sentences < 8 words
    long_sentence_ratio: float = 0.0       # sentences > 25 words
    vocabulary_richness: float = 0.0       # type-token ratio
    signature_phrases: list[str] = Field(default_factory=list)
    punctuation_style: dict[str, float] = Field(default_factory=dict)
    pov_pronouns: list[str] = Field(default_factory=list)
    dialogue_ratio: float = 0.0
    raw_summary: str = ""


class TextChange(BaseModel):
    change_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pass_number: int
    paragraph_index: int
    sentence_range: tuple[int, int] | None = None
    original: str
    proposed: str
    rationale: str
    craft_principle: str
    voice_alert: bool = False
    voice_conflict: bool = False
    inline_diff_html: str = ""
    status: Literal["pending", "accepted", "rejected"] = "pending"


class PassResult(BaseModel):
    pass_number: int
    changes: list[TextChange] = Field(default_factory=list)
    pass_summary: str = ""


class ChapterSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    original_text: str
    current_text: str
    voice_fingerprint: VoiceFingerprint | None = None
    pass_results: list[PassResult] = Field(default_factory=list)
    humanizer_alerts: list[TextChange] = Field(default_factory=list)
    status: Literal[
        "uploaded", "analyzing", "pass1", "pass2", "pass3", "audit", "complete"
    ] = "uploaded"
    last_pending_change_id: str | None = None
