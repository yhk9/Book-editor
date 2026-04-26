from __future__ import annotations
import re

AI_VOCABULARY_BANNED: list[str] = [
    "actually", "additionally", "testament", "landscape", "delve", "tapestry",
    "vibrant", "pivotal", "groundbreaking", "seamlessly", "robust", "utilize",
    "leverage", "paradigm", "game-changer", "innovative", "revolutionize",
    "notable", "noteworthy", "it's worth noting", "it is worth noting",
    "importantly", "crucially", "essentially", "fundamentally", "ultimately",
    "certainly", "undoubtedly", "unquestionably", "needless to say",
    "in conclusion", "to summarize", "in summary", "in essence",
    "dive into", "let's dive", "deep dive", "let's explore",
    "shed light", "stands out", "rest assured", "I want to clarify",
    "I hope this", "hope this helps", "feel free to",
]

ANTI_PATTERNS: list[dict] = [
    {
        "id": 1, "name": "Significance inflation",
        "description": (
            "Avoid dramatic framing like 'pivotal moment', 'groundbreaking', "
            "'landmark event', or 'historic'. These inflate importance without "
            "evidence. State what happened; let the reader judge the magnitude."
        ),
    },
    {
        "id": 2, "name": "Notability name-dropping",
        "description": (
            "Citing a list of outlet names ('covered by CNN, BBC, Reuters...') "
            "without actual quotes or specifics. Either cite a real source with "
            "context, or drop the attribution entirely."
        ),
    },
    {
        "id": 3, "name": "Superficial -ing analyses",
        "description": (
            "Phrases like 'highlighting the importance of', 'demonstrating the "
            "need for', or 'underscoring the value of' that gesture at analysis "
            "without providing it. Remove or replace with actual evidence."
        ),
    },
    {
        "id": 4, "name": "Promotional language",
        "description": (
            "Adjectives that read like marketing copy: 'innovative', 'cutting-edge', "
            "'state-of-the-art', 'best-in-class'. Use neutral, descriptive language."
        ),
    },
    {
        "id": 5, "name": "Vague attributions",
        "description": (
            "'Experts say', 'studies show', 'researchers found' without naming "
            "the expert, study, or researcher. Either name the source or delete "
            "the claim."
        ),
    },
    {
        "id": 6, "name": "Formulaic challenges",
        "description": (
            "Boilerplate obstacle framing: 'However, challenges remain', "
            "'Despite these advances, hurdles persist'. Provide specific facts "
            "about what the challenges actually are."
        ),
    },
    {
        "id": 7, "name": "AI vocabulary",
        "description": (
            "Words and phrases statistically overused by AI: 'actually', "
            "'additionally', 'testament', 'landscape', 'delve', 'tapestry', "
            "'vibrant', 'seamlessly', 'robust', 'leverage', 'utilize'. "
            "Replace with plain, precise language."
        ),
    },
    {
        "id": 8, "name": "Copula avoidance",
        "description": (
            "AI avoids 'is' and 'has' in favor of elaborate constructions: "
            "'serves as a testament to', 'boasts an impressive array of', "
            "'stands as a beacon of'. Prefer 'is', 'has', or rewrite directly."
        ),
    },
    {
        "id": 9, "name": "Negative parallelisms",
        "description": (
            "The pattern 'It's not X, it's Y' or 'Not only X but Y'. These "
            "sound rhetorical and mechanical. State the positive claim directly."
        ),
    },
    {
        "id": 10, "name": "Rule of three",
        "description": (
            "Forcing items into groups of exactly three: 'speed, accuracy, and "
            "efficiency'. Real writing uses natural counts. Two or four items "
            "are often more honest."
        ),
    },
    {
        "id": 11, "name": "Synonym cycling",
        "description": (
            "Rotating through synonyms to avoid repetition: 'the scientist... "
            "the researcher... the academic...'. Clear writing repeats the "
            "precise term rather than cycling through alternatives."
        ),
    },
    {
        "id": 12, "name": "False ranges",
        "description": (
            "'Topics ranging from X to Y' when only two examples are given, "
            "or the range is arbitrary. List the topics directly."
        ),
    },
    {
        "id": 13, "name": "Passive voice / subjectless fragments",
        "description": (
            "Hiding the actor: 'It was decided that...', 'Changes were made...', "
            "'Efforts are underway...'. Name who decided, who changed, who is "
            "making the effort."
        ),
    },
    {
        "id": 14, "name": "Em dash overuse",
        "description": (
            "More than one or two em dashes per page creates a choppy, "
            "AI-generated feel. Replace excess em dashes with commas, "
            "semicolons, or periods."
        ),
    },
    {
        "id": 15, "name": "Boldface overuse",
        "description": (
            "Bolding random phrases for emphasis rather than using prose "
            "structure to create emphasis. Minimize or eliminate inline bold "
            "in narrative prose."
        ),
    },
    {
        "id": 16, "name": "Inline-header lists",
        "description": (
            "Embedding bold headers inside flowing prose to organize it: "
            "'**First**, we see that... **Second**...'. Convert to natural "
            "prose transitions."
        ),
    },
    {
        "id": 17, "name": "Title case headings",
        "description": (
            "Using title case for every heading word: 'The Importance Of "
            "Consistent Voice In Fiction'. Use standard sentence case."
        ),
    },
    {
        "id": 18, "name": "Emojis",
        "description": (
            "Emojis in prose or headings signal AI generation. Remove entirely "
            "from literary fiction and serious nonfiction."
        ),
    },
    {
        "id": 19, "name": "Curly quote inconsistency",
        "description": (
            "Mixing curly quotes and straight quotes, or using curly apostrophes "
            "inconsistently. Standardize to straight quotes for plain text output."
        ),
    },
    {
        "id": 20, "name": "Chatbot artifacts",
        "description": (
            "Residue of assistant-mode writing: 'I hope this helps!', "
            "'Feel free to ask', 'Great question!', 'Certainly!'. "
            "These have no place in prose. Delete."
        ),
    },
    {
        "id": 21, "name": "Cutoff disclaimers",
        "description": (
            "'As of my knowledge cutoff...', 'I may not have the latest "
            "information...'. Either find a real source or delete the claim."
        ),
    },
    {
        "id": 22, "name": "Sycophantic tone",
        "description": (
            "Opening responses or sections with flattery: 'What a fascinating "
            "question', 'Excellent point', 'You're absolutely right'. "
            "Respond directly."
        ),
    },
    {
        "id": 23, "name": "Filler phrases",
        "description": (
            "Bloat without meaning: 'in order to' (→ 'to'), 'the fact that' "
            "(→ cut), 'it is important to note that' (→ cut), 'at the end of "
            "the day' (→ cut). Every word must earn its place."
        ),
    },
    {
        "id": 24, "name": "Excessive hedging",
        "description": (
            "Stacking qualifiers: 'it might possibly be somewhat likely that "
            "perhaps...'. One qualifier per claim is the maximum. Consolidate "
            "or commit to the claim."
        ),
    },
    {
        "id": 25, "name": "Generic conclusions",
        "description": (
            "Endings that restate the obvious: 'In conclusion, we have seen "
            "that...', 'Ultimately, it's clear that...'. End with a specific "
            "fact, image, or forward-looking question."
        ),
    },
    {
        "id": 26, "name": "Hyphenated word pairs",
        "description": (
            "Hyphenating common compound modifiers unnecessarily: 'well-known', "
            "'widely-used', 'high-quality' when they follow the noun. Follow "
            "standard usage; most post-noun compounds are unhyphenated."
        ),
    },
    {
        "id": 27, "name": "Persuasive authority tropes",
        "description": (
            "'As any expert will tell you', 'Everyone knows that', "
            "'It goes without saying'. These assert authority without evidence. "
            "State the claim and provide the evidence."
        ),
    },
    {
        "id": 28, "name": "Signposting announcements",
        "description": (
            "Meta-commentary about what the text is about to do: "
            "'Let's dive in', 'Now let's turn to', 'In the next section we "
            "will examine'. Skip the announcement; just do the thing."
        ),
    },
    {
        "id": 29, "name": "Fragmented headers",
        "description": (
            "Headings that are sentence fragments requiring the body text to "
            "complete them. Each heading should be self-contained."
        ),
    },
]

_CATEGORY_GROUPS = {
    "Content": [1, 2, 3, 4, 5, 6],
    "Language": [7, 8, 9, 10, 11, 12, 13],
    "Style & Formatting": [14, 15, 16, 17, 18, 19],
    "Filler & Hedging": [20, 21, 22, 23, 24, 25, 26, 27, 28, 29],
}


def build_humanizer_rules_block() -> str:
    lines: list[str] = [
        "HUMANIZER RULES — DO NOT INTRODUCE THESE AI-WRITING PATTERNS:\n"
    ]
    pattern_map = {p["id"]: p for p in ANTI_PATTERNS}
    for category, ids in _CATEGORY_GROUPS.items():
        lines.append(f"{category} patterns:")
        for pid in ids:
            p = pattern_map[pid]
            lines.append(f"  {pid}. {p['name']}: {p['description']}")
        lines.append("")
    lines.append(
        "Banned vocabulary (replace immediately if found): "
        + ", ".join(f'"{w}"' for w in AI_VOCABULARY_BANNED[:20])
        + "."
    )
    return "\n".join(lines)


def build_humanizer_audit_prompt(text: str, fingerprint_summary: str) -> str:
    return (
        f"The author's voice fingerprint:\n{fingerprint_summary}\n\n"
        "Review the chapter below for any surviving AI-writing anti-patterns "
        "from the rules provided in the system prompt. "
        "For each pattern you find, return a change proposal. "
        "If the text is clean, return an empty changes list.\n\n"
        f"CHAPTER TEXT:\n{text}"
    )


def scan_banned_vocabulary(text: str) -> list[dict]:
    results = []
    lower = text.lower()
    for word in AI_VOCABULARY_BANNED:
        positions = [m.start() for m in re.finditer(re.escape(word.lower()), lower)]
        if positions:
            results.append({"word": word, "count": len(positions), "positions": positions})
    return results
