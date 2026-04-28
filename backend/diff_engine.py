from __future__ import annotations
import difflib
import re
from backend.models import TextChange, PassResult


def split_into_paragraphs(text: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in paragraphs if p.strip()]


def split_into_sentences(paragraph: str) -> list[str]:
    # Simple sentence splitter that respects common abbreviations
    pattern = r'(?<!\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc|approx|incl|excl|dept|est|vol|no|pp))\.'
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"])', paragraph)
    return [s.strip() for s in parts if s.strip()]


def compute_inline_diff(original: str, proposed: str) -> str:
    orig_words = original.split()
    prop_words = proposed.split()
    matcher = difflib.SequenceMatcher(None, orig_words, prop_words)
    parts: list[str] = []
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "equal":
            parts.append(" ".join(orig_words[i1:i2]))
        elif opcode == "replace":
            parts.append(f'<del class="del">{" ".join(orig_words[i1:i2])}</del>')
            parts.append(f'<ins class="ins">{" ".join(prop_words[j1:j2])}</ins>')
        elif opcode == "delete":
            parts.append(f'<del class="del">{" ".join(orig_words[i1:i2])}</del>')
        elif opcode == "insert":
            parts.append(f'<ins class="ins">{" ".join(prop_words[j1:j2])}</ins>')
    return " ".join(parts)


def apply_changes_to_text(original_text: str, accepted_changes: list[TextChange]) -> str:
    paragraphs = split_into_paragraphs(original_text)
    sorted_changes = sorted(accepted_changes, key=lambda c: c.paragraph_index, reverse=True)

    for change in sorted_changes:
        idx = change.paragraph_index
        if idx >= len(paragraphs):
            continue
        if not change.proposed.strip():
            # Empty proposed = flag for manual expansion; skip
            continue

        if change.sentence_range is None:
            # Whole-paragraph replacement
            paragraphs[idx] = change.proposed
        else:
            sentences = split_into_sentences(paragraphs[idx])
            start, end = change.sentence_range
            end = min(end, len(sentences))
            prop_sentences = split_into_sentences(change.proposed)
            paragraphs[idx] = " ".join(
                sentences[:start] + prop_sentences + sentences[end:]
            )

    return "\n\n".join(paragraphs)


def group_changes_by_paragraph(changes: list[TextChange]) -> dict[int, list[TextChange]]:
    grouped: dict[int, list[TextChange]] = {}
    for change in changes:
        grouped.setdefault(change.paragraph_index, []).append(change)
    return grouped


def serialize_pass_result_for_sse(pass_result: PassResult) -> list[dict]:
    events = []
    for change in pass_result.changes:
        diff_html = compute_inline_diff(change.original, change.proposed)
        d = change.model_dump()
        d["inline_diff_html"] = diff_html
        events.append(d)
    return events


def batch_text(text: str, max_words: int = 800) -> list[tuple[int, str]]:
    """Split long chapters into (start_paragraph_index, batch_text) tuples."""
    paragraphs = split_into_paragraphs(text)
    batches: list[tuple[int, str]] = []
    current: list[str] = []
    current_words = 0
    start_idx = 0

    for i, para in enumerate(paragraphs):
        word_count = len(para.split())
        if current and current_words + word_count > max_words:
            batches.append((start_idx, "\n\n".join(current)))
            start_idx = i
            current = [para]
            current_words = word_count
        else:
            current.append(para)
            current_words += word_count

    if current:
        batches.append((start_idx, "\n\n".join(current)))

    return batches
