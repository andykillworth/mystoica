#!/usr/bin/env python3
"""
Mystoica pipeline script.

Called three times a day (matins / sext / vespers) by GitHub Actions.
1. Calls Claude with web search enabled, asking for a structured JSON reading
   built from real, obscure public-record sources.
2. Fills that content into reading_template.html.
3. Writes the result to readings/YYYY-MM-DD-<slot>.html
4. Regenerates index.html (today's three dispatches) and archive.html (full list).
"""

import os
import sys
import json
import re
import requests
from datetime import datetime, timezone

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"  # swap to claude-opus-4-8 for higher quality at higher cost

SLOT_INFO = {
    "matins": {"label": "Matins", "suffix": "M", "hour": "07:00"},
    "sext":   {"label": "Sext",   "suffix": "S", "hour": "13:00"},
    "vespers":{"label": "Vespers","suffix": "V", "hour": "19:00"},
}

SYSTEM_PROMPT = """You are the generating engine behind Mystoica, a daily art project.

Your job: search real, obscure public records from TODAY or the last few days —
small-town police blotters, USDA/FSIS recall notices, patent filings, fire
department dispatch logs, court dockets, USPTO trademark filings. NEVER use
mainstream press (no AP, Reuters, NYT, CNN, BBC, etc). The more obscure and
hyperlocal the source, the better.

Find exactly THREE real, unrelated facts from three different obscure sources.
Then invent a symbolic reading, a numerology exercise, a "custody chain" theory,
and a 5-step cascade narrative connecting them — written with total sincerity,
never winking at the reader, never explaining that this is satire.

Voice rules:
- Confident, declarative, literary. Never hedge.
- The facts must be 100% real and cited with a real working URL.
- The connections must be invented, but delivered as if genuine.
- Follow the exact JSON schema given. Output ONLY valid JSON, no preamble,
  no markdown fences, nothing else.

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

def build_user_prompt(slot: str, date_str: str) -> str:
    info = SLOT_INFO[slot]
    return (
        f"Generate today's {info['label']} reading for {date_str}. "
        f"This is the {slot} dispatch ({info['hour']} slot). "
        "Search for real, obscure, current sources and build the JSON reading now."
    )

def call_claude(slot: str, date_str: str) -> dict:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": 8000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_user_prompt(slot, date_str)}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    full_text = "\n".join(text_blocks).strip()

    # extract just the JSON object, in case the model added any stray text around it
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
        return json.loads(json_str)
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

def render_page(reading: dict, slot: str, date_str: str, case_no: str) -> str:
    with open("templates/reading_template.html", "r", encoding="utf-8") as f:
        tpl = f.read()

    info = SLOT_INFO[slot]
    replacements = {
        "__TITLE__": f"Mystoica — {info['label']} Reading, {date_str}",
        "__HOUR_LABEL__": f"{info['label']} — a reading, three times daily",
        "__CASE_NO__": case_no,
        "__SOURCED_WINDOW__": f"Sourced around {info['hour']}",
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
        "__NEXT_READING_NOTE__": f"Next: {_next_slot_label(slot)}",
    }
    for token, value in replacements.items():
        tpl = tpl.replace(token, value)
    return tpl

def _next_slot_label(slot: str) -> str:
    order = ["matins", "sext", "vespers"]
    idx = order.index(slot)
    if idx == len(order) - 1:
        return "tomorrow, Matins"
    return SLOT_INFO[order[idx + 1]]["label"]

def regenerate_homepage(date_str: str, case_date: str):
    """Rebuilds index.html listing today's three slots with correct statuses/links."""
    order = ["matins", "sext", "vespers"]
    cards = []
    now_slot = os.environ.get("CURRENT_SLOT")
    for slot in order:
        info = SLOT_INFO[slot]
        path = f"readings/{case_date}-{slot}.html"
        exists = os.path.exists(path)
        is_current = slot == now_slot
        css_class = "dispatch latest" if is_current else ("dispatch past" if exists else "dispatch past")
        status = "live now" if is_current else ("" if exists else "pending")
        teaser = _extract_teaser(path) if exists else "Not yet filed."
        link_open = f'<a class="{css_class}" href="/{path}">' if exists else f'<div class="{css_class}" style="opacity:0.5;cursor:default;">'
        link_close = "</a>" if exists else "</div>"
        read_link = '<span class="read-link">Full reading →</span>' if exists else "<span></span>"
        status_html = f'<span class="status-pill">{status}</span>' if status else ""
        cards.append(f'''    {link_open}
      <div class="dispatch-top">
        <span class="hour-badge">{info['label']} — {case_date.replace('-', '.')[2:]}-{info['suffix']}</span>
        <span class="hour-time">{info['hour']}</span>
      </div>
      <p class="dispatch-teaser">{teaser}</p>
      <div class="dispatch-foot">
        <span>{status_html}</span>
        {read_link}
      </div>
    {link_close}''')

    with open("templates/homepage_template.html", "r", encoding="utf-8") as f:
        tpl = f.read()
    tpl = tpl.replace("__DATE_DISPLAY__", date_str)
    tpl = tpl.replace("__CASE_NO__", case_date.replace("-", "."))
    tpl = tpl.replace("__DISPATCH_CARDS__", "\n\n".join(cards))

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(tpl)

def _extract_teaser(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'class="cascade-outro">(.*?)</p>', content, re.S)
    return m.group(1).strip() if m else "Read the full reading."

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
        date_part = parts[0] if len(parts) == 2 else label
        slot_part = parts[1] if len(parts) == 2 else ""
        slot_display = slot_labels.get(slot_part, slot_part.capitalize())
        rows.append(f'''    <a class="archive-row" href="/readings/{fname}">
      <span class="archive-date">{date_part}<span class="archive-slot">{slot_display}</span></span>
      <span class="archive-arrow">→</span>
    </a>''')

    with open("templates/archive_template.html", "r", encoding="utf-8") as f:
        tpl = f.read()
    tpl = tpl.replace("__ARCHIVE_ROWS__", "\n\n".join(rows))

    with open("archive.html", "w", encoding="utf-8") as f:
        f.write(tpl)

def main():
    if len(sys.argv) < 2:
        print("Usage: generate_reading.py <matins|sext|vespers>")
        sys.exit(1)

    slot = sys.argv[1]
    os.environ["CURRENT_SLOT"] = slot
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %B %-d, %Y")
    case_date = now.strftime("%Y-%m-%d")
    case_no = f"{now.strftime('%Y.%m%d')}-{SLOT_INFO[slot]['suffix']}"

    print(f"Generating {slot} reading for {case_date}...")
    reading = call_claude(slot, date_str)

    os.makedirs("readings", exist_ok=True)
    page_html = render_page(reading, slot, date_str, case_no)
    out_path = f"readings/{case_date}-{slot}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page_html)
    print(f"Wrote {out_path}")

    regenerate_homepage(date_str, case_date)
    regenerate_archive()
    print("Homepage and archive regenerated.")

if __name__ == "__main__":
    main()
