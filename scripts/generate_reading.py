#!/usr/bin/env python3
"""
Mystoica pipeline script.

Called once a day by an external scheduler.
1. Scans previous readings to build a list of already-used sources.
2. Calls Claude with web search enabled (capped at 5 searches, to control cost),
   asking for a structured JSON reading built from real, obscure public-record
   sources NOT already used.
3. Fills that content into reading_template.html.
4. Writes the result to readings/YYYY-MM-DD.html AND to index.html (the homepage).
5. Regenerates archive.html (full list of past readings).
"""

import os
import json
import re
import requests
from datetime import datetime, timezone

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"  # swap to claude-opus-4-8 for higher quality at higher cost
SITE_URL = "https://mystoica.com"

SYSTEM_PROMPT = """You are the generating engine behind Mystoica, a daily art project.

Your job: search real, obscure public records from TODAY or the last few days —
small-town police blotters, USDA/FSIS recall notices, patent filings, fire
department dispatch logs, court dockets, USPTO trademark filings. NEVER use
mainstream press (no AP, Reuters, NYT, CNN, BBC, etc). The more obscure and
hyperlocal the source, the better.

You have a LIMITED budget of web searches (5 max) for this task. Use them
efficiently — search with specific, targeted queries rather than broad ones,
and stop as soon as you have three good, distinct, real facts. Do not use
every available search if you don't need to.

Find exactly THREE real, unrelated facts from three different obscure sources.
CRITICAL: you will be given a list of sources/facts already used in previous
readings. You must NOT reuse any of them.

Then invent a symbolic reading, a numerology exercise, a "custody chain" theory,
and a 5-step cascade narrative connecting them — written with total sincerity,
never winking at the reader, never explaining that this is satire.

Voice rules:
- Confident, declarative, literary. Never hedge.
- The facts must be 100% real and cited with a real working URL.
- The connections must be invented, but delivered as if genuine.
- Follow the exact JSON schema given. Output ONLY valid, strictly well-formed
  JSON — no preamble, no markdown fences, nothing else. All text values must
  be single-line: never include literal newlines or raw control characters
  inside a string; use plain spaces instead of line breaks within any value.

JSON schema:
{
  "exhibits": [
    {"tag": "Exhibit A — Filed", "location": "City, State", "fact": "...",
     "source_name": "...", "source_url": "..."},
    ... exactly 3 ...
  ],
  "intro": "one sentence, italic voice, sets up the three exhibits",
  "symbols": [
    {"label": "A — The Thing", "text": "symbolic gloss, 1-2 sentences"},
    ... exactly 3, matching exhibit order ...
  ],
  "symbol_synthesis": "1-2 sentence synthesis tying the three symbols together",
  "numbers": [
    {"label": "description of where the number came from", "reduction": "single digit or short value"},
    ... 4 or 5 numbers pulled from the real facts/sources ...
  ],
  "num_callout": "1 sentence noting any repeated digit, or noting there isn't one",
  "num_synthesis": "1-2 sentence interpretation of the numerology",
  "theory_text": "the working theory paragraph, can reuse/riff on the standing Adjacency Clause idea",
  "cascade_intro": "short line introducing the custody trace",
  "cascade_steps": [
    {"location": "City, State (optional, only on relevant steps)", "text": "..."},
    ... exactly 5 ...
  ],
  "cascade_outro": "closing italic verdict line",
  "stamp_label": "two short words for the seal, e.g. 'so noted' or 'so it follows'"
}
"""

def get_used_sources(limit_files: int = 30) -> list:
    """Scans past reading files and pulls out every source URL and fact snippet
    already used, so the model can be told to avoid repeating them."""
    if not os.path.isdir("readings"):
        return []
    files = sorted(os.listdir("readings"), reverse=True)[:limit_files]
    used = []
    for fname in files:
        if not fname.endswith(".html"):
            continue
        path = os.path.join("readings", fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        urls = re.findall(r'exhibit-source">.*?href="([^"]+)"', content, re.S)
        facts = re.findall(r'exhibit-fact">(.*?)</p>', content, re.S)
        for u in urls:
            used.append(f"URL: {u}")
        for fact in facts:
            snippet = re.sub(r"<[^>]+>", "", fact).strip()
            used.append(f"FACT: {snippet[:140]}")
    return used

def build_user_prompt(date_str: str, used_sources: list) -> str:
    exclusion_block = ""
    if used_sources:
        joined = "\n".join(f"- {s}" for s in used_sources[:60])
        exclusion_block = (
            "\n\nThe following sources/facts have ALREADY been used in previous "
            "readings. Do not reuse any of them — find different, fresh obscure "
            f"sources instead:\n{joined}\n"
        )
    return (
        f"Generate today's reading for {date_str}. "
        "Search for real, obscure, current sources and build the JSON reading now."
        f"{exclusion_block}"
    )

def call_claude(date_str: str, used_sources: list) -> dict:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": 6000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_user_prompt(date_str, used_sources)}],
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    full_text = "\n".join(text_blocks).strip()

    start = full_text.find("{")
    end = full_text.rfind("}")
    if start == -1 or end == -1:
        print("---- RAW MODEL OUTPUT (no JSON object found) ----")
        print(full_text if full_text else "(empty response)")
        print("---- STOP REASON ----")
        print(data.get("stop_reason"))
        print("--------------------------------------------------")
        raise ValueError("No JSON object found in model output")

    json_str = full_text[start:end + 1]
    try:
        return json.loads(json_str, strict=False)
    except json.JSONDecodeError:
        print("---- RAW MODEL OUTPUT (failed to parse as JSON) ----")
        print(full_text)
        print("-----------------------------------------------------")
        raise

def render_exhibits(exhibits: list) -> str:
    threads = [
        '<svg width="60" height="16" viewBox="0 0 60 16"><path d="M0 8 Q 30 -4 60 8" stroke="#8a3226" stroke-width="1" fill="none" stroke-dasharray="2 3" opacity="0.6"/></svg>',
        '<svg width="60" height="16" viewBox="0 0 60 16"><path d="M0 8 Q 30 20 60 8" stroke="#8a3226" stroke-width="1" fill="none" stroke-dasharray="2 3" opacity="0.6"/></svg>',
    ]
    parts = []
    for i, ex in enumerate(exhibits):
        parts.append(f'''    <div class="exhibit">
      <div class="exhibit-tag">{ex["tag"]}</div>
      <div class="exhibit-loc">{ex["location"]}</div>
      <p class="exhibit-fact">{ex["fact"]}</p>
      <div class="exhibit-source">
        <span>{ex["source_name"]}</span>
        <a href="{ex["source_url"]}" target="_blank" rel="noopener">{ex["source_url"].split('/')[2]} ↗</a>
      </div>
    </div>''')
        if i < len(exhibits) - 1:
            parts.append(f'    <div class="thread-row">\n      {threads[i % 2]}\n    </div>')
    return "\n\n".join(parts)

def render_symbols(symbols: list) -> str:
    parts = []
    for s in symbols:
        parts.append(f'''      <div class="symbol-item">
        <dt>{s["label"]}</dt>
        <dd>{s["text"]}</dd>
      </div>''')
    return "\n".join(parts)

def render_numerology_rows(numbers: list) -> str:
    rows = []
    for n in numbers:
        rows.append(f'        <tr><td>{n["label"]}</td><td class="num-reduce">→ {n["reduction"]}</td></tr>')
    return "\n".join(rows)

def render_cascade_steps(steps: list) -> str:
    parts = []
    for i, s in enumerate(steps, start=1):
        loc_html = f'<span class="cascade-loc">{s["location"]}</span> — ' if s.get("location") else ""
        parts.append(f'''      <div class="cascade-step">
        <div class="cascade-node">{i}</div>
        <p>{loc_html}{s["text"]}</p>
      </div>''')
    return "\n".join(parts)

def render_page(reading: dict, date_str: str, case_no: str, canonical_url: str) -> str:
    with open("templates/reading_template.html", "r", encoding="utf-8") as f:
        tpl = f.read()

    replacements = {
        "__TITLE__": f"Mystoica — Reading for {date_str}",
        "__CANONICAL_URL__": canonical_url,
        "__CASE_NO__": case_no,
        "__INTRO__": reading["intro"],
        "__EXHIBITS_HTML__": render_exhibits(reading["exhibits"]),
        "__SYMBOLS_HTML__": render_symbols(reading["symbols"]),
        "__SYMBOL_SYNTHESIS__": reading["symbol_synthesis"],
        "__NUMEROLOGY_ROWS__": render_numerology_rows(reading["numbers"]),
        "__NUM_CALLOUT__": reading["num_callout"],
        "__NUM_SYNTHESIS__": reading["num_synthesis"],
        "__THEORY_TEXT__": reading["theory_text"],
        "__CASCADE_INTRO__": reading["cascade_intro"],
        "__CASCADE_STEPS_HTML__": render_cascade_steps(reading["cascade_steps"]),
        "__CASCADE_OUTRO__": reading["cascade_outro"],
        "__STAMP_LABEL__": reading["stamp_label"].replace(" ", "<br>", 1),
    }
    for token, value in replacements.items():
        tpl = tpl.replace(token, value)
    return tpl

def regenerate_archive():
    """Rebuilds archive.html by listing every file in readings/, newest first."""
    if not os.path.isdir("readings"):
        return
    files = sorted(os.listdir("readings"), reverse=True)
    slot_labels = {"matins": "Matins", "sext": "Sext", "vespers": "Vespers"}
    rows = []
    for fname in files:
        if not fname.endswith(".html"):
            continue
        label = fname.replace(".html", "")
        parts = label.rsplit("-", 1)
        if len(parts) == 2 and parts[1] in slot_labels:
            date_part, slot_part = parts
            slot_display = slot_labels[slot_part]
        else:
            date_part, slot_display = label, ""
        badge = f'<span class="archive-slot">{slot_display}</span>' if slot_display else ""
        rows.append(f'''    <a class="archive-row" href="/readings/{fname}">
      <span class="archive-date">{date_part}{badge}</span>
      <span class="archive-arrow">→</span>
    </a>''')

    with open("templates/archive_template.html", "r", encoding="utf-8") as f:
        tpl = f.read()
    tpl = tpl.replace("__ARCHIVE_ROWS__", "\n\n".join(rows))

    with open("archive.html", "w", encoding="utf-8") as f:
        f.write(tpl)

def main():
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %B %-d, %Y")
    case_date = now.strftime("%Y-%m-%d")
    case_no = now.strftime("%Y.%m%d")

    used_sources = get_used_sources()
    print(f"Found {len(used_sources)} previously-used source references to exclude.")

    print(f"Generating reading for {case_date}...")
    reading = call_claude(date_str, used_sources)

    os.makedirs("readings", exist_ok=True)
    out_path = f"readings/{case_date}.html"
    archived_canonical = f"{SITE_URL}/{out_path}"
    page_html = render_page(reading, date_str, case_no, archived_canonical)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page_html)
    print(f"Wrote {out_path}")

    # index.html is the same content, but canonicalized to the site root
    homepage_html = page_html.replace(archived_canonical, f"{SITE_URL}/")
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(homepage_html)
    print("Wrote index.html")

    regenerate_archive()
    print("Archive regenerated.")

if __name__ == "__main__":
    main()
