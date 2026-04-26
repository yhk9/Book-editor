from __future__ import annotations
import json
import re
import math
import anthropic
from backend.models import VoiceFingerprint
from backend.humanizer import build_humanizer_rules_block

VOICE_ANALYSIS_SYSTEM = """You are a literary analyst specializing in author voice fingerprinting.
Analyze the provided chapter and extract a precise fingerprint of the author's unique writing style.

Detect and return as JSON:
- avg_sentence_length: average words per sentence (float)
- short_sentence_ratio: fraction of sentences under 8 words (float 0-1)
- long_sentence_ratio: fraction of sentences over 25 words (float 0-1)
- vocabulary_richness: type-token ratio (unique words / total words, float 0-1)
- signature_phrases: up to 10 recurring multi-word phrases or stylistic tics (list of strings)
- punctuation_style: dict of punctuation marks to frequency per 100 words, e.g. {"em_dash": 0.5, "ellipsis": 0.2, "semicolon": 0.1}
- pov_pronouns: dominant POV markers, e.g. ["he", "she"] for third-person close, ["I"] for first-person
- dialogue_ratio: fraction of text inside quotation marks (float 0-1)
- raw_summary: one paragraph (3-5 sentences) describing this author's voice in concrete, specific terms — rhythm, register, characteristic moves

Return ONLY valid JSON matching that schema. No extra keys. No explanation outside the JSON."""


def _build_voice_messages(chapter_text: str) -> list[dict]:
    return [{"role": "user", "content": f"Analyze the voice in this chapter:\n\n{chapter_text}"}]


def compute_local_metrics(text: str) -> dict:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s for s in sentences if s.strip()]
    if not sentences:
        return {}

    word_counts = [len(s.split()) for s in sentences]
    total_words = sum(word_counts)
    words = re.findall(r"\b[a-zA-Z']+\b", text.lower())
    unique_words = set(words)

    em_dashes = text.count("—") + text.count("--")
    ellipses = text.count("…") + text.count("...")
    semicolons = text.count(";")
    dialogue_chars = sum(
        len(m.group()) for m in re.finditer(r'"[^"]*"', text)
    )

    return {
        "avg_sentence_length": total_words / len(sentences) if sentences else 0.0,
        "short_sentence_ratio": sum(1 for w in word_counts if w < 8) / len(sentences),
        "long_sentence_ratio": sum(1 for w in word_counts if w > 25) / len(sentences),
        "vocabulary_richness": len(unique_words) / len(words) if words else 0.0,
        "punctuation_style": {
            "em_dash": round(em_dashes / total_words * 100, 3) if total_words else 0,
            "ellipsis": round(ellipses / total_words * 100, 3) if total_words else 0,
            "semicolon": round(semicolons / total_words * 100, 3) if total_words else 0,
        },
        "dialogue_ratio": dialogue_chars / len(text) if text else 0.0,
    }


def voice_conflict_score(proposed_text: str, fingerprint: VoiceFingerprint) -> float:
    local = compute_local_metrics(proposed_text)
    if not local:
        return 0.0

    score = 0.0
    checks = 0

    def _delta(a: float, b: float, threshold: float) -> float:
        return min(abs(a - b) / (threshold + 1e-9), 1.0)

    if fingerprint.avg_sentence_length > 0:
        score += _delta(local["avg_sentence_length"], fingerprint.avg_sentence_length, 5.0)
        checks += 1

    if fingerprint.short_sentence_ratio >= 0:
        score += _delta(local["short_sentence_ratio"], fingerprint.short_sentence_ratio, 0.3)
        checks += 1

    if fingerprint.long_sentence_ratio >= 0:
        score += _delta(local["long_sentence_ratio"], fingerprint.long_sentence_ratio, 0.3)
        checks += 1

    if fingerprint.vocabulary_richness > 0:
        score += _delta(local["vocabulary_richness"], fingerprint.vocabulary_richness, 0.2)
        checks += 1

    return score / checks if checks else 0.0


async def analyze_voice(
    client: anthropic.AsyncAnthropic,
    chapter_text: str,
    model: str,
) -> VoiceFingerprint:
    local = compute_local_metrics(chapter_text)
    messages = _build_voice_messages(chapter_text)
    system = [
        {
            "type": "text",
            "text": VOICE_ANALYSIS_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=messages,
        betas=["prompt-caching-2024-07-31"],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback to local metrics only
        data = {}

    # Merge local metrics as ground truth for numeric fields
    merged = {
        "avg_sentence_length": local.get("avg_sentence_length", data.get("avg_sentence_length", 0.0)),
        "short_sentence_ratio": local.get("short_sentence_ratio", data.get("short_sentence_ratio", 0.0)),
        "long_sentence_ratio": local.get("long_sentence_ratio", data.get("long_sentence_ratio", 0.0)),
        "vocabulary_richness": local.get("vocabulary_richness", data.get("vocabulary_richness", 0.0)),
        "signature_phrases": data.get("signature_phrases", []),
        "punctuation_style": local.get("punctuation_style", data.get("punctuation_style", {})),
        "pov_pronouns": data.get("pov_pronouns", []),
        "dialogue_ratio": local.get("dialogue_ratio", data.get("dialogue_ratio", 0.0)),
        "raw_summary": data.get("raw_summary", "Voice analysis unavailable."),
    }
    return VoiceFingerprint(**merged)
