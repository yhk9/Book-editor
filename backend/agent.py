from __future__ import annotations
import asyncio
import uuid
from typing import AsyncGenerator
import anthropic

from backend.models import ChapterSession, TextChange, PassResult, VoiceFingerprint
from backend.storage import save_session
from backend.voice_analyzer import analyze_voice, voice_conflict_score
from backend.passes import (
    build_pass_messages,
    build_audit_messages,
    parse_pass_result,
)
from backend.diff_engine import (
    apply_changes_to_text,
    serialize_pass_result_for_sse,
    batch_text,
)
from backend.humanizer import scan_banned_vocabulary

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192
DECISION_TIMEOUT = 300  # seconds user has to approve/reject each change
MAX_WORDS_PER_BATCH = 800


class BookEditorAgent:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str = MODEL):
        self.client = client
        self.model = model

    async def run_session(
        self,
        session: ChapterSession,
        queue: asyncio.Queue,
    ) -> AsyncGenerator[dict, None]:
        try:
            async for event in self._run(session, queue):
                yield event
        except asyncio.CancelledError:
            yield _event("error", {"message": "Session cancelled."})
        except Exception as exc:
            yield _event("error", {"message": str(exc)})

    async def _run(
        self,
        session: ChapterSession,
        queue: asyncio.Queue,
    ) -> AsyncGenerator[dict, None]:
        # ── Phase 0: voice analysis ──────────────────────────────────────────
        session.status = "analyzing"
        save_session(session)
        yield _event("status", {"phase": "analyzing", "message": "Analyzing author voice…"})

        fingerprint = await analyze_voice(self.client, session.original_text, self.model)
        session.voice_fingerprint = fingerprint
        save_session(session)
        yield _event("voice", fingerprint.model_dump())

        banned_found = scan_banned_vocabulary(session.original_text)
        if banned_found:
            yield _event("status", {
                "phase": "analyzing",
                "message": f"Found {len(banned_found)} banned vocabulary item(s) to fix.",
            })

        # ── Phases 1-3: editing passes ───────────────────────────────────────
        pass_names = {1: "Structure & Pacing", 2: "Voice & Tone", 3: "Line-Level Polish"}
        previous_summary = ""

        for pass_number in [1, 2, 3]:
            status_key = f"pass{pass_number}"
            session.status = status_key  # type: ignore[assignment]
            save_session(session)

            yield _event("pass_start", {
                "pass": pass_number,
                "name": pass_names[pass_number],
                "total_passes": 3,
            })

            pass_result = await self._run_pass(
                pass_number,
                session.current_text,
                fingerprint,
                previous_summary,
            )

            # Mark voice alerts based on local conflict score
            for change in pass_result.changes:
                if change.proposed:
                    score = voice_conflict_score(change.proposed, fingerprint)
                    if score > 0.6 or change.voice_conflict:
                        change.voice_alert = True

            # Present changes to user one at a time
            accepted: list[TextChange] = []
            sse_events = serialize_pass_result_for_sse(pass_result)

            for i, event_data in enumerate(sse_events):
                change = pass_result.changes[i]
                event_data["total_in_pass"] = len(pass_result.changes)
                event_data["index_in_pass"] = i

                session.last_pending_change_id = change.change_id
                save_session(session)
                yield _event("change", event_data)

                decision = await _await_decision(queue, change.change_id)
                change.status = decision
                if decision == "accepted":
                    accepted.append(change)
                yield _event("decision", {"change_id": change.change_id, "status": decision})

            # Apply accepted changes and accumulate into current_text
            if accepted:
                session.current_text = apply_changes_to_text(session.current_text, accepted)

            session.pass_results.append(pass_result)
            session.last_pending_change_id = None
            save_session(session)

            previous_summary = pass_result.pass_summary
            yield _event("pass_complete", {
                "pass": pass_number,
                "name": pass_names[pass_number],
                "pass_summary": pass_result.pass_summary,
                "accepted": len(accepted),
                "total": len(pass_result.changes),
            })

        # ── Phase 4: humanizer audit ─────────────────────────────────────────
        session.status = "audit"
        save_session(session)
        yield _event("audit_start", {"step": 1, "message": "Running humanizer audit…"})

        audit_changes = await self._run_humanizer_audit(
            session.current_text,
            fingerprint,
        )
        session.humanizer_alerts = audit_changes

        accepted_audit: list[TextChange] = []
        audit_sse = serialize_pass_result_for_sse(
            PassResult(pass_number=4, changes=audit_changes, pass_summary="Humanizer audit")
        )

        for i, event_data in enumerate(audit_sse):
            change = audit_changes[i]
            event_data["total_in_pass"] = len(audit_changes)
            event_data["index_in_pass"] = i
            event_data["pass_number"] = 4
            event_data["pass_name"] = "Audit"

            session.last_pending_change_id = change.change_id
            save_session(session)
            yield _event("change", event_data)

            decision = await _await_decision(queue, change.change_id)
            change.status = decision
            if decision == "accepted":
                accepted_audit.append(change)
            yield _event("decision", {"change_id": change.change_id, "status": decision})

        if accepted_audit:
            session.current_text = apply_changes_to_text(session.current_text, accepted_audit)

        # ── Complete ─────────────────────────────────────────────────────────
        session.status = "complete"
        session.last_pending_change_id = None
        save_session(session)

        total_accepted = sum(
            sum(1 for c in pr.changes if c.status == "accepted")
            for pr in session.pass_results
        ) + len(accepted_audit)
        total_changes = sum(len(pr.changes) for pr in session.pass_results) + len(audit_changes)

        yield _event("complete", {
            "final_text": session.current_text,
            "stats": {
                "total_changes_proposed": total_changes,
                "total_accepted": total_accepted,
                "total_rejected": total_changes - total_accepted,
            },
        })

    async def _run_pass(
        self,
        pass_number: int,
        current_text: str,
        fingerprint: VoiceFingerprint,
        previous_summary: str,
    ) -> PassResult:
        word_count = len(current_text.split())
        if word_count <= MAX_WORDS_PER_BATCH * 1.2:
            return await self._single_pass_call(
                pass_number, current_text, fingerprint, previous_summary
            )
        # Batch large chapters
        return await self._batched_pass_call(
            pass_number, current_text, fingerprint, previous_summary
        )

    async def _single_pass_call(
        self,
        pass_number: int,
        text: str,
        fingerprint: VoiceFingerprint,
        previous_summary: str,
    ) -> PassResult:
        messages, system = build_pass_messages(pass_number, text, fingerprint, previous_summary)
        raw = await self._stream_and_collect(messages, system)
        return parse_pass_result(raw, pass_number)

    async def _batched_pass_call(
        self,
        pass_number: int,
        text: str,
        fingerprint: VoiceFingerprint,
        previous_summary: str,
    ) -> PassResult:
        batches = batch_text(text, max_words=MAX_WORDS_PER_BATCH)
        all_changes: list[TextChange] = []
        summaries: list[str] = []

        for batch_start_idx, batch_text_chunk in batches:
            messages, system = build_pass_messages(
                pass_number, batch_text_chunk, fingerprint, previous_summary
            )
            raw = await self._stream_and_collect(messages, system)
            result = parse_pass_result(raw, pass_number)
            # Offset paragraph indices to match the full text
            for change in result.changes:
                change.paragraph_index += batch_start_idx
            all_changes.extend(result.changes)
            summaries.append(result.pass_summary)

        return PassResult(
            pass_number=pass_number,
            changes=all_changes,
            pass_summary=" ".join(summaries[:2]),
        )

    async def _run_humanizer_audit(
        self,
        text: str,
        fingerprint: VoiceFingerprint,
    ) -> list[TextChange]:
        all_changes: list[TextChange] = []
        seen_originals: set[str] = set()

        for step in [1, 2]:
            messages, system = build_audit_messages(step, text, fingerprint.raw_summary)
            raw = await self._stream_and_collect(messages, system)
            result = parse_pass_result(raw, pass_number=4)
            for change in result.changes:
                if change.original not in seen_originals:
                    seen_originals.add(change.original)
                    all_changes.append(change)

        return all_changes

    async def _stream_and_collect(
        self,
        messages: list[dict],
        system: list[dict],
    ) -> str:
        accumulated = ""
        async with self.client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            betas=["prompt-caching-2024-07-31"],
        ) as stream:
            async for text in stream.text_stream:
                accumulated += text
        return accumulated


async def _await_decision(queue: asyncio.Queue, change_id: str) -> str:
    while True:
        try:
            decision = await asyncio.wait_for(queue.get(), timeout=DECISION_TIMEOUT)
        except asyncio.TimeoutError:
            return "rejected"  # timeout = auto-reject, keep original
        if decision.get("change_id") == change_id:
            return decision.get("status", "rejected")
        # Put back unrelated decisions (shouldn't happen, but safety net)
        await queue.put(decision)
        await asyncio.sleep(0.05)


def _event(event_type: str, data: dict) -> dict:
    return {"event": event_type, "data": data}
