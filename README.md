# Book Chapter Editor

An AI agent that edits your novel chapters while preserving your voice. Upload a chapter, and it runs three structured editing passes — each proposed change shown as a before/after diff that you approve or reject one at a time.

---

## Quick start

```bash
git clone https://github.com/yhk9/Book-editor.git
cd Book-editor
bash install.sh
```

The installer checks your Python version, installs dependencies, creates a `.env` file, and sets up the Claude Code skill. Then:

1. Open `.env` and paste your Anthropic API key:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```
   Get one free at [console.anthropic.com](https://console.anthropic.com) → API Keys.

2. Start the server:
   ```bash
   uvicorn backend.main:app --reload
   ```

3. Open **http://localhost:8000** and drop in a `.txt` chapter.

---

## Two ways to use it

| | Web app | Claude Code skill |
|---|---|---|
| How to start | `uvicorn backend.main:app` | `/book-editor` |
| Interface | Browser with visual diffs | Claude Code terminal |
| Needs API key | Yes (`ANTHROPIC_API_KEY`) | No — uses your Claude session |
| Best for | Visual review, sharing | Quick edits inside Claude Code |

---

## Web app walkthrough

### 1 — Upload your chapter

Drag a `.txt` file onto the sidebar upload zone, or click to browse. Plain text only; up to 5 MB (configurable). The agent starts automatically.

### 2 — Review the voice fingerprint

After a few seconds, a **Voice Fingerprint** card appears. Click to expand it:

```
VOICE FINGERPRINT
────────────────────────────────────────
Average sentence length  8.1 words
Short sentence ratio     41%  (< 8 words)
POV / pronouns           she, her
Dialogue ratio           12%
Signature phrases        "she held", "nothing happened", ...
Register                 clipped declarative, minimal punctuation
────────────────────────────────────────
Summary: This author writes in a tight third-person close, favoring
short declarative sentences that accumulate pressure through repetition...
```

This fingerprint governs all three passes. Every proposed edit is measured against it — edits that deviate from your style get a ⚠ **Voice Alert** badge.

### 3 — Work through the changes

Each proposed change appears as a card:

```
┌──────────────────────────────────────────────────────┐
│ PASS 1 · Structure & Pacing              Change 2/7  │
│ Craft: Chapter-end hook                              │
│ ──────────────────────────────────────────────────── │
│ BEFORE                                               │
│  She put the key in the lock. Nothing happened.      │
│ ──────────────────────────────────────────────────── │
│ AFTER (word-level diff)                              │
│  She slid the key in. The lock [refused to] turn.   │
│ ──────────────────────────────────────────────────── │
│ WHY: Sentence rhythm — tension beat needs compression │
│                                                      │
│  [  Reject  ]                   [  Accept  ]        │
└──────────────────────────────────────────────────────┘
```

- Green = words added · Red strikethrough = words removed
- **Accept** applies the change and moves to the next
- **Reject** keeps your original and moves to the next
- **Skip remaining in this pass** rejects all pending changes in the current pass

The agent waits for your decision before showing the next change. Nothing is applied without your approval.

### 4 — The three passes

| Pass | Focus |
|------|-------|
| **1 · Structure & Pacing** | Scene order, momentum, chapter-end hooks, LOCK framework, show-don't-tell |
| **2 · Voice & Tone** | Dialogue subtext, sensory specificity, POV consistency, emotional beats |
| **3 · Line-Level Polish** | Filler phrases, weak verbs, banned AI vocabulary, rhythm, grammar |

After the three passes a **Humanizer Audit** runs automatically — two sweeps for AI-writing anti-patterns (significance inflation, em dash overuse, sycophantic phrasing, and 26 others).

### 5 — Download

When complete, click **Download Edited Chapter** to save the final `.txt`. Only your approved changes are in it.

---

## Claude Code skill

If you use Claude Code, the `/book-editor` skill is installed automatically by `install.sh` and works without any server or API key.

```
/book-editor path/to/chapter.txt
```

or just `/book-editor` — Claude will ask for the file.

**To install the skill manually:**
```bash
mkdir -p ~/.claude/skills/book-editor
cp .claude/skills/book-editor/SKILL.md ~/.claude/skills/book-editor/SKILL.md
```

The skill runs the same workflow (voice fingerprint → 3 passes → audit) interactively in your terminal, showing each change and waiting for `y` / `n` before proceeding.

---

## Configuration

All settings can be set in `.env`:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-api03-...

# Optional
ANTHROPIC_BASE_URL=https://api.anthropic.com   # Custom API endpoint
ANTHROPIC_TIMEOUT=120                           # API call timeout (seconds)
EDITOR_MODEL=claude-sonnet-4-6                  # Claude model to use
EDITOR_MAX_TOKENS=8192                          # Max tokens per API call
EDITOR_DECISION_TIMEOUT=300                     # Seconds before auto-rejecting a change
EDITOR_BATCH_WORDS=800                          # Words per batch for long chapters
MAX_UPLOAD_MB=5                                 # Max chapter file size
MAX_SESSIONS=100                                # Max concurrent sessions stored
CORS_ORIGINS=https://yourdomain.com             # Comma-separated allowed origins
```

---

## Tips

**Use full chapters, not excerpts.** The voice fingerprinter needs at least 500 words to detect your patterns accurately. Longer is better.

**Be selective in Pass 1.** Structural changes (scene reorders, cuts) are the hardest to undo. When unsure, reject and decide manually.

**Voice Alerts deserve a second look.** They mean the proposed text has different rhythm or vocabulary from the rest of your chapter. Sometimes that's fine — sometimes it means the AI is drifting from your voice.

**Accept Pass 3 changes freely.** Filler phrase cuts and weak-verb replacements are low-risk. Review the WHY and accept if it sounds right.

**One chapter at a time.** Each session builds a voice profile from its uploaded chapter. Running separate sessions keeps each chapter's voice analysis clean.

---

## Sessions

Sessions are listed in the sidebar and persist between server restarts. Click any session to return to it. If your browser disconnects mid-session, reload — the last unanswered change is replayed automatically.

Delete a session with the **✕** button. The server also caps sessions at `MAX_SESSIONS` (default 100) to prevent unbounded growth.

---

## Troubleshooting

**"No API key found"**
Add `ANTHROPIC_API_KEY=sk-ant-api03-...` to your `.env` file and restart the server.

**Nothing happens after upload**
Check the terminal running `uvicorn` for error output. A missing API key or network issue will show up there.

**Voice fingerprint looks wrong**
This can happen with very short chapters or chapters that mix multiple POVs. Use the full chapter and the analysis improves.

**Download produces the original text**
All changes were rejected — which is fine. Your chapter was already clean, or you chose to keep your originals.

**Server won't start — "port already in use"**
```bash
# Use a different port
uvicorn backend.main:app --port 8001 --reload
```

---

## Architecture

```
Browser  ←── SSE stream ──── FastAPI  ──── Anthropic API
   │                            │
   └─── POST /decision ─────────┘
         (accept / reject)    asyncio.Queue
```

| File | Role |
|------|------|
| `backend/agent.py` | Orchestrates the loop: voice analysis → 3 passes → audit. Yields SSE events, awaits decisions via `asyncio.Queue` |
| `backend/passes.py` | System prompts for all 3 passes + humanizer audit, with `cache_control: ephemeral` prompt caching |
| `backend/voice_analyzer.py` | Voice fingerprinting via Claude + local sentence metrics |
| `backend/humanizer.py` | All 29 AI-writing anti-pattern rules, injected into every system prompt |
| `backend/diff_engine.py` | Word-level HTML diff (with HTML escaping) and change application engine |
| `backend/storage.py` | Atomic filesystem session persistence with UUID path validation |
| `backend/main.py` | FastAPI routes, security headers, input validation, SSE endpoint, decision endpoint |
| `frontend/index.html` | Single-page app (Tailwind CDN, no build step needed) |
| `frontend/static/app.js` | SSE client, change card rendering, accept/reject, session list |
| `.claude/skills/book-editor/SKILL.md` | Portable Claude Code skill (no server required) |

---

## Requirements

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com)
- A modern browser (Chrome, Firefox, Safari, Edge)
