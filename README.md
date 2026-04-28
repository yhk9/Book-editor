# Book Chapter Editor

An AI agent that edits your novel chapters while preserving your voice. It runs three structured passes over each chapter, shows you every proposed change as a before/after diff, and applies only the ones you approve.

---

## What it does

1. **Fingerprints your voice** — before touching a single word, it reads your chapter and extracts a precise profile of your writing style: average sentence length, punctuation habits, signature phrases, POV, dialogue ratio. Every edit is measured against this fingerprint.

2. **Runs three editing passes**, each focused on a different level:
   - **Pass 1 — Structure & Pacing**: scene order, momentum, chapter-end hooks, the LOCK framework (Lead / Objective / Confrontation / Knockout), show-don't-tell
   - **Pass 2 — Voice & Tone**: dialogue subtext, sensory specificity, POV consistency, register alignment, emotional beats shown rather than stated
   - **Pass 3 — Line-Level Polish**: filler phrases, weak verb+adverb pairs, banned AI vocabulary, sentence rhythm, grammar, punctuation

3. **Asks you before applying anything** — each proposed change appears as a highlighted diff. You click Accept or Reject. The agent waits for your decision before moving to the next change.

4. **Runs a humanizer audit** at the end — a two-pass sweep for the 29 most common AI-writing anti-patterns (significance inflation, rule of three, em dash overuse, sycophantic phrasing, etc.)

5. **Flags voice conflicts** — if a proposed edit would alter your characteristic sentence rhythm or punctuation style, it gets a ⚠ Voice Alert badge so you can scrutinize it more carefully.

---

## Setup

### Requirements

- Python 3.11+
- An Anthropic API key (`sk-ant-api03-...` from [console.anthropic.com](https://console.anthropic.com))

### Install

```bash
git clone https://github.com/yhk9/Book-editor.git
cd Book-editor
pip install -r requirements.txt
```

### Configure your API key

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Open `.env` and paste your key:

```
ANTHROPIC_API_KEY=sk-ant-api03-...
```

### Start the server

```bash
uvicorn backend.main:app --reload
```

Open your browser at **http://localhost:8000**

---

## How to use it

### 1. Upload a chapter

Drag and drop a `.txt` file onto the upload zone in the left sidebar, or click the zone to browse. The file should be plain text — one chapter at a time works best.

The agent starts automatically once the file is uploaded.

### 2. Review the voice fingerprint

After a few seconds, a **Voice Fingerprint** card appears at the top of the main panel. Click it to expand. It shows what the AI detected about your writing style — average sentence length, signature phrases, POV markers, dialogue ratio. This fingerprint governs every edit the agent proposes.

If the fingerprint looks wrong (e.g. it misidentified your POV), you can still use the tool — just be more aggressive about rejecting changes that don't sound like you.

### 3. Work through the changes

Each proposed change appears as a card:

```
┌─────────────────────────────────────────┐
│ PASS 1 · Structure & Pacing      1 / 7  │
│ Craft principle: Chapter-end hook       │
│                                         │
│ BEFORE                                  │
│  She put the key in the lock.           │
│  Nothing happened.                      │
│                                         │
│ AFTER (word-level diff)                 │
│  She slid the key in.                   │
│  The lock ~~didn't~~ **refused to** turn│
│                                         │
│ WHY: Sentence rhythm — tension beat     │
│                                         │
│  [REJECT]              [ACCEPT]         │
└─────────────────────────────────────────┘
```

- **Green highlights** = words added
- **Red strikethrough** = words removed
- The **WHY** line explains the craft reasoning behind each change
- A **⚠ Voice Alert** badge (amber border) means the edit deviates from your detected style — review these carefully

Click **Accept** to apply the change, **Reject** to keep your original. The agent moves to the next change only after you decide.

### 4. Skip a pass

If you want to skip all remaining changes in the current pass, click **Skip remaining changes in this pass** at the bottom of any change card. All pending changes in that pass are rejected and the next pass begins.

### 5. Download the result

When all passes and the humanizer audit are complete, a **Download Edited Chapter** button appears. Click it to save the final `.txt` file with only your approved changes applied.

---

## Tips for best results

**Use a full chapter, not an excerpt.** The voice fingerprinter needs enough text to detect your patterns accurately — at least 500 words, ideally 1,000+.

**Accept sparingly in Pass 1.** Structural changes are the hardest to undo. If you're unsure about a scene reorder or a cut, reject it and decide manually.

**Trust Voice Alerts.** If a change gets flagged ⚠, it means the proposed text has different rhythm or vocabulary from the rest of your chapter. It might still be a good suggestion, but read it carefully before accepting.

**Reject early, accept late.** Pass 3 (line-level) changes are safer to accept freely — a filler phrase cut or a weak verb swap rarely breaks anything. Pass 1 structural changes deserve more scrutiny.

**Run one chapter at a time.** The agent builds up a picture of your voice from the uploaded chapter. Running multiple chapters in separate sessions gives each chapter its own voice analysis.

---

## Sessions

Your sessions are listed in the sidebar and persist between server restarts. You can:

- **Click a session** to return to it
- **✕** next to a session name to delete it

If your browser disconnects mid-session, reload the page — the last unanswered change will be replayed automatically.

---

## Architecture

```
browser ←── SSE stream ──── FastAPI ──── Claude (Anthropic API)
   │                           │
   └── POST /decision ─────────┘
         (accept/reject)   asyncio.Queue
```

| File | Role |
|------|------|
| `backend/agent.py` | Orchestrates the full loop: voice analysis → 3 passes → audit. Yields SSE events, awaits decisions via `asyncio.Queue` |
| `backend/passes.py` | System prompts for all 3 passes + humanizer audit, with prompt caching via `cache_control: ephemeral` |
| `backend/voice_analyzer.py` | Fingerprints author voice using Claude + local sentence metrics |
| `backend/humanizer.py` | All 29 AI-writing anti-pattern rules, injected into every system prompt |
| `backend/diff_engine.py` | Word-level HTML diff, paragraph-level change application |
| `backend/main.py` | FastAPI routes: upload, SSE stream, decision endpoint, download |
| `frontend/index.html` | Single-page app (Tailwind CDN, no build step) |
| `frontend/static/app.js` | SSE client, change card rendering, accept/reject logic |

---

## Troubleshooting

**"No API key found"** — make sure `ANTHROPIC_API_KEY` is set in your `.env` file and the server was restarted after you added it.

**Voice fingerprint looks wrong** — this can happen with very short chapters or chapters that mix multiple POVs. Use the full chapter and the analysis will be more accurate.

**A change card never appears** — the agent may be waiting on a large Claude response. Give it up to 30 seconds per pass. Check the server terminal for error output.

**Download produces the original text** — this means all changes were rejected. That's fine — it means your chapter was already clean.
