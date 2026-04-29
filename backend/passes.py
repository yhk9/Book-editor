from __future__ import annotations
import json
import re
from backend.models import VoiceFingerprint, PassResult, TextChange
from backend.humanizer import build_humanizer_rules_block

_HUMANIZER_BLOCK = build_humanizer_rules_block()

_PASS1_STATIC = f"""You are an expert fiction editor specializing in narrative structure.
You are editing a single chapter of a novel for STRUCTURE AND PACING ONLY.

AUTHOR VOICE PRESERVATION — HIGHEST PRIORITY:
Every edit you propose must stay consistent with the author's voice fingerprint.
If a structural improvement would require changing the author's characteristic sentence
rhythm, punctuation style, or vocabulary register, do NOT make that change — note it
in the rationale as "Voice conflict: skipped."

{_HUMANIZER_BLOCK}

BEST-SELLER CRAFT PRINCIPLES FOR THIS PASS:
Scene is the fundamental unit of fiction — ninety percent of a good novel is written
in scene. Does every scene in this chapter serve plot or character?

Pacing follows peaks and valleys. Identify where the chapter drags (over-explanation,
redundant beats, lingering after the emotional peak) and where it rushes (skipping
beats the reader needs to feel).

Chapter-end hook: the final paragraph should pull the reader forward with an
unresolved question, a shift in stakes, or a charged image. If it doesn't, propose
a revision.

LOCK framework: every chapter should give the Lead a clear Objective, put that
objective in Confrontation, and end on a Knockout — a moment that changes something.
If any LOCK element is absent or weak, flag it.

Show don't tell: scenes that summarize action or emotion instead of dramatizing it
should be flagged. If the fix is simple, propose it. If it requires full scene
expansion, return an empty proposed string so the author knows to expand manually.

WHAT TO CHANGE IN THIS PASS:
- Scenes that drag: cut redundant setup and over-explained transitions.
- Scenes that rush: note where expansion is needed (empty proposed string).
- Chapter ending: propose a hook revision if needed.
- Do NOT touch sentence-level grammar, word choice, or dialogue subtext.
  Those are Pass 2 and 3 concerns.

OUTPUT FORMAT:
Return ONLY a valid JSON object with exactly two keys: "pass_summary" and "changes".
pass_summary: two sentences describing what this pass changed.
changes: array of objects, each with:
  paragraph_index (int), sentence_range (null or [start, end] int array),
  original (string), proposed (string), rationale (string), craft_principle (string).
If proposed is empty it means the author should expand that passage manually.
Do not include any text outside the JSON."""

_PASS2_STATIC = f"""You are an expert fiction editor whose mission is to deepen and protect
the author's distinctive voice while improving tonal consistency.

{_HUMANIZER_BLOCK}

BEST-SELLER CRAFT PRINCIPLES FOR THIS PASS:
Subtext in dialogue: what characters do NOT say is as important as what they say.
Propose trims or rewrites where dialogue is too on-the-nose — where a character
explains their feelings instead of revealing them through action or deflection.

Sensory specificity: a single concrete detail grounds the reader more than three
vague adjectives. Replace atmospheric filler with one precise sensory image.

Narrative distance: is the POV consistent? Flag and correct any head-hopping or
unearned omniscient intrusion.

Emotional beats: the author's voice should carry the emotion without stating it.
Flag lines that name the emotion ("she felt devastated") and propose a version
that shows it through behavior, sensation, or environment.

Register consistency: if one paragraph sounds more formal or more colloquial
than the surrounding prose, align it to the chapter's dominant register.

WHAT TO CHANGE IN THIS PASS:
- Generic-sounding lines: propose a version that sounds like THIS author.
- Dialogue that overstates: propose a subtext version.
- Vague sensory descriptions: replace with one specific detail.
- POV inconsistencies: correct to established POV.
- Tonal inconsistencies: align to dominant register.
- Do NOT restructure scenes or reorder paragraphs (Pass 1 concern).
- Do NOT make line-level grammar corrections (Pass 3 concern).

VOICE ALERT RULE:
If a proposed change feels uncharacteristic of the author's fingerprint (shortening
sentences for an author with long rolling syntax, adding em dashes for one who uses
none), add "voice_conflict": true to that change object.

OUTPUT FORMAT:
Return ONLY a valid JSON object with exactly two keys: "pass_summary" and "changes".
pass_summary: two sentences.
changes: array of objects, each with:
  paragraph_index (int), sentence_range (null or [start, end]),
  original (string), proposed (string), rationale (string),
  craft_principle (string), and optionally voice_conflict (bool).
Do not include any text outside the JSON."""

_PASS3_STATIC = f"""You are a line editor and prose stylist making final micro-level corrections.
The chapter has already been structurally and tonally edited in earlier passes.

{_HUMANIZER_BLOCK}

Your primary targets in this pass are the humanizer anti-patterns above. Hunt for
and eliminate every surviving AI-writing pattern.

BEST-SELLER CRAFT PRINCIPLES FOR THIS PASS:
Sentence rhythm: vary length deliberately. Short sentences punch. Long sentences
breathe. Match rhythm to the emotional temperature of the moment. If the prose
around a climax is all long sentences, tighten them.

Opening lines of each paragraph must pull the reader forward. A paragraph that
begins with a weak, generic sentence loses the reader's eye.

Cut filler: "in order to" → "to". "the fact that" → cut. "it was" constructions
→ active rewrite. Every word must earn its place.

Cut adverbs that weaken strong verbs. "ran quickly" → "sprinted". "said quietly"
→ "murmured". Find the precise verb.

Precision over vagueness: replace generic nouns with specific ones. "a vehicle"
→ "a rusted Camry". "a building" → "the brick postal annex".

Grammar: fix subject-verb agreement errors, tense inconsistencies, and comma
splices that survived earlier passes.

Rhythm audit: any sentence that would stumble when read aloud should be rewritten.

WHAT TO CHANGE IN THIS PASS:
- Banned AI vocabulary: replace every instance immediately.
- Filler phrases and redundant qualifiers: cut or replace.
- Weak verb+adverb pairs: replace with a single strong verb.
- Passive constructions: activate where it doesn't flatten the voice.
- Grammar and punctuation errors.
- Sentence rhythm misfires: rewrite for better cadence.
- Em dash overuse (more than 2 per page): convert some to commas or colons.
- Do NOT restructure scenes or change the author's tonal register.

OUTPUT FORMAT:
Return ONLY a valid JSON object with exactly two keys: "pass_summary" and "changes".
pass_summary: two sentences.
changes: array of objects, each with:
  paragraph_index (int), sentence_range (null or [start, end]),
  original (string), proposed (string), rationale (string), craft_principle (string).
Do not include any text outside the JSON."""

_AUDIT1_STATIC = f"""You are an AI-writing detection specialist and line editor.
A chapter has been through three rounds of human-guided editing. Find any surviving
AI-writing patterns from the rules below and propose natural replacements.

{_HUMANIZER_BLOCK}

Return ONLY valid JSON: {{"pass_summary": str, "changes": [...]}}
Each change: paragraph_index, sentence_range (null or [start, end]),
original, proposed, rationale, craft_principle."""

_AUDIT2_STATIC = f"""Read this chapter as a sharp-eyed human reader encountering it for the first time.
Ask: does any sentence sound like it was written by an AI? Does any phrasing feel
unnatural, over-polished, or like a chatbot attempted to be literary?

Focus on:
- Sentence openings that all follow the same syntactic pattern
- Metaphors that feel forced or generic rather than earned
- Any word a real author of this genre would never use
- Over-smooth transitions that feel automated
- Anything that breaks the spell of the author's established voice

{_HUMANIZER_BLOCK}

Return ONLY valid JSON: {{"pass_summary": str, "changes": [...]}}
Each change: paragraph_index, sentence_range, original, proposed, rationale, craft_principle."""


def build_system_split_cache(static_part: str, dynamic_part: str) -> list[dict]:
    return [
        {"type": "text", "text": static_part, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_part},
    ]


def build_pass_messages(
    pass_number: int,
    chapter_text: str,
    voice_fingerprint: VoiceFingerprint,
    previous_summary: str = "",
) -> tuple[list[dict], list[dict]]:
    fp_json = voice_fingerprint.model_dump_json(indent=2)
    dynamic = f"\nAUTHOR VOICE FINGERPRINT:\n{fp_json}\n"

    if previous_summary:
        dynamic += f"\nPREVIOUS PASS SUMMARY:\n{previous_summary}\n"

    statics = {1: _PASS1_STATIC, 2: _PASS2_STATIC, 3: _PASS3_STATIC}
    system = build_system_split_cache(statics[pass_number], dynamic)

    messages = [
        {
            "role": "user",
            "content": f"Edit the following chapter (Pass {pass_number}):\n\n{chapter_text}",
        }
    ]
    return messages, system


def build_audit_messages(
    audit_step: int,
    chapter_text: str,
    fingerprint_summary: str,
) -> tuple[list[dict], list[dict]]:
    static = _AUDIT1_STATIC if audit_step == 1 else _AUDIT2_STATIC
    dynamic = f"\nAUTHOR VOICE SUMMARY:\n{fingerprint_summary}\n"
    system = build_system_split_cache(static, dynamic)
    messages = [
        {
            "role": "user",
            "content": f"Audit this chapter for AI-writing patterns:\n\n{chapter_text}",
        }
    ]
    return messages, system


def parse_pass_result(raw_json: str, pass_number: int) -> PassResult:
    raw = raw_json.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    # Find the first complete JSON object (non-greedy to avoid merging multiple)
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
    if not match:
        return PassResult(pass_number=pass_number, pass_summary="Parse error — no changes applied.")

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return PassResult(pass_number=pass_number, pass_summary="Parse error — no changes applied.")

    changes: list[TextChange] = []
    for item in data.get("changes", []):
        try:
            sr = item.get("sentence_range")
            changes.append(
                TextChange(
                    pass_number=pass_number,
                    paragraph_index=int(item.get("paragraph_index", 0)),
                    sentence_range=tuple(sr) if sr and len(sr) == 2 else None,
                    original=str(item.get("original", "")),
                    proposed=str(item.get("proposed", "")),
                    rationale=str(item.get("rationale", "")),
                    craft_principle=str(item.get("craft_principle", "")),
                    voice_conflict=bool(item.get("voice_conflict", False)),
                )
            )
        except Exception:
            continue

    return PassResult(
        pass_number=pass_number,
        changes=changes,
        pass_summary=str(data.get("pass_summary", "")),
    )
