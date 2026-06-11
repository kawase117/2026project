#!/usr/bin/env python3
"""
Session archive extractor for Claude Code session logs.
Generates searchable Markdown documents from JSONL transcripts.
Optimized for Claude's grep/search retrieval patterns.
"""

import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional

PROJECTS_DIR = Path.home() / ".claude" / "projects"
OUTPUT_DIR = Path.cwd() / "document" / "sessions"

# Session titles retrieved from list_sessions MCP (2026-05-29)
# Format: {"<uuid>": "<title>"}
SESSION_TITLES = {
    "9e50ff6a-d6a0-4510-9982-eea8d532bcc0": "Sunday machine strategy analysis",
    "6615d62d-b4ce-45c2-868a-5f4994119522": "GitHub push verification",
    "897930c1-aa30-429c-8213-7b82661b9f3b": "instinct-export timing and automation",
    "527e5334-898b-4e68-8a30-74ca76dc31d3": "蒲田七 2026-05-27 予測分析",
    "866f62a6-ce79-40f6-b4df-b2b4f1a29274": "Pachinko data analysis brainstorm",
    "a0518519-35b0-4c82-b08d-139b7fcea445": "Fix is_zorome description in CLAUDE.md",
    "f31ee4c0-9759-4076-a0f8-d74b7026ce8d": "末尾ゾロ目複合シミュレーション",
    "da4f713b-7103-466b-9c63-c4f893d0941b": "機種別学習: 特徴量選別と2F/3F差分",
    "d1bc3703-b115-485b-b779-a2bdc947ab08": "機種別学習2",
    "eacc0880-8101-4ad6-baa3-0c6b0a4e1634": "機種別学習",
    "4023a302-d62f-46f8-bfe5-d7fd8ddf20e2": "末尾学習4",
    "e3fc5662-0145-41d5-b15b-74c5817c8854": "Slot machine selection strategy",
    "8eda07f2-f631-47b0-9a4f-47bd892c0f4c": "URL difference in ANA SLO scraper",
    "82ba9160-3d4e-482b-b5de-1ca7a3b84e22": "機種別学習データ探索",
    "8ebda28e-575e-44b8-906e-fbc7be78f658": "末尾学習3",
    "461a85a4-3690-4360-b32e-d9580c12e191": "末尾学習データ探索",
    "1fee4a16-e76d-4f5c-af3a-8a5466f47aae": "末尾学習2",
    "704b0b93-210a-4ae7-a98d-5308dfdc1d0d": "末尾別学習",
    "6c521c0e-ea07-4bef-b49d-9d92e1001f22": "機種別学習",
    "8a3e9123-2881-4423-a303-d5d1e493d88b": "Instinct import",
    "116caed5-d1be-45ca-9e16-35c12edbb17c": "Review and refactor last digit ML code",
    "9f1501d9-e41a-41fe-8dfa-4e0cde5c82e1": "Investigate BT flag logic in database code",
    "6de7a53b-495e-4acd-8faf-fbf1940802b3": "Scan and list unnecessary files for cleanup",
    "8f2a6942-6ac5-4fda-8a6c-0a85d1dfe17c": "Run multi-threaded web scraper for analysis",
    "5a9a078a-942f-413a-829b-923de5000891": "Evaluate CodeGraph repository for project use",
    "a2fee9dc-c48f-45b9-a64e-e0cee8b117be": "Fix database subtable updates in incremental updater",
    "bb500922-0781-4b22-a992-1068b4e49805": "Implement instinct import feature",
    "0afb36b3-cfd3-4427-91ca-dfc4b89f4541": "Review store optimized pipeline code",
    "b0a8ce8a-c772-4f05-8f4c-6e93fe6962d4": "Restore accidentally deleted feature engineering file",
}

# Keywords to identify decision/fix/design content
SIGNAL_KEYWORDS = [
    # Decisions
    "決定", "設計", "採用", "方針", "推奨",
    # Fixes
    "修正", "バグ", "解決", "fix", "fixed", "resolved",
    # Implementation
    "実装", "追加", "implement", "added", "完了",
    # ML-specific
    "hit@", "NDCG", "AUC", "ECE", "CatBoost", "walk-forward",
    "hit_at_1", "hit_at_2", "ndcg", "lift",
    # Architecture
    "アーキテクチャ", "pipeline", "パイプライン", "特徴量",
    "segment", "セグメント", "expert", "エキスパート",
]


def extract_session_id(session_data: list) -> Optional[str]:
    """Get session UUID from JSONL data."""
    for entry in session_data[:20]:
        sid = entry.get("sessionId", "")
        if sid and len(sid) == 36 and sid.count("-") == 4:
            return sid
    return None


def get_timestamp(session_data: list) -> str:
    """Get earliest timestamp from session."""
    for entry in session_data:
        ts = entry.get("timestamp", "")
        if ts and len(ts) >= 10:
            return ts[:10]
    return "unknown"


def extract_user_messages(session_data: list) -> list[str]:
    """Extract user messages from queue-operation/enqueue entries."""
    messages = []
    for entry in session_data:
        if (entry.get("type") == "queue-operation"
                and entry.get("operation") == "enqueue"):
            content = entry.get("content", "")
            if content and len(content.strip()) > 5:
                messages.append(content.strip())
    return messages


def extract_assistant_text(session_data: list) -> list[str]:
    """Extract assistant text blocks from message.content[].text entries."""
    texts = []
    for entry in session_data:
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})
        if not isinstance(msg, dict):
            continue
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text and len(text.strip()) > 20:
                    texts.append(text.strip())
    return texts


def score_text(text: str) -> int:
    """Score text by number of signal keywords present."""
    lower = text.lower()
    return sum(1 for kw in SIGNAL_KEYWORDS if kw.lower() in lower)


def pick_key_paragraphs(texts: list[str], max_paragraphs: int = 5) -> list[str]:
    """Select the most informative paragraphs from assistant responses."""
    scored = []
    for text in texts:
        # Split into paragraphs
        for para in re.split(r"\n{2,}", text):
            para = para.strip()
            if 40 < len(para) < 1500:
                s = score_text(para)
                if s > 0:
                    scored.append((s, para))
    scored.sort(key=lambda x: -x[0])
    # Deduplicate by first 80 chars
    seen = set()
    result = []
    for _, para in scored:
        key = para[:80]
        if key not in seen:
            seen.add(key)
            result.append(para)
            if len(result) >= max_paragraphs:
                break
    return result


def format_session_block(session_id: str, title: str, date: str,
                         user_msgs: list[str], key_paras: list[str]) -> str:
    """Format one session as a Markdown section."""
    lines = []
    lines.append(f"### {date} | {title}")
    lines.append(f"**session_id**: `{session_id}`")
    lines.append("")

    if user_msgs:
        lines.append("**User requests**:")
        for msg in user_msgs[:3]:
            first_line = msg.split("\n")[0][:120]
            lines.append(f"- {first_line}")
        lines.append("")

    if key_paras:
        lines.append("**Key decisions / changes**:")
        lines.append("")
        for para in key_paras:
            lines.append(para)
            lines.append("")
    else:
        lines.append("_No high-signal content detected._")
        lines.append("")

    return "\n".join(lines)


def main():
    jsonl_files = sorted(
        PROJECTS_DIR.glob("**/*.jsonl"),
        key=lambda p: p.stat().st_mtime
    )

    if not jsonl_files:
        print("No session files found.")
        return

    print(f"Processing {len(jsonl_files)} session files...")

    sessions_by_month: dict[str, list[dict]] = defaultdict(list)
    total_extracted = 0

    for i, path in enumerate(jsonl_files):
        if (i + 1) % 20 == 0:
            print(f"  [{i + 1}/{len(jsonl_files)}] ...")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = [json.loads(ln) for ln in f if ln.strip()]
        except Exception:
            continue

        if not data:
            continue

        session_id = extract_session_id(data) or path.stem
        date = get_timestamp(data)
        month = date[:7] if date != "unknown" else "undated"
        title = SESSION_TITLES.get(session_id, f"Session {session_id[:8]}")

        user_msgs = extract_user_messages(data)
        asst_texts = extract_assistant_text(data)
        key_paras = pick_key_paragraphs(asst_texts)

        sessions_by_month[month].append({
            "id": session_id,
            "title": title,
            "date": date,
            "user_msgs": user_msgs,
            "key_paras": key_paras,
            "path": str(path),
        })
        total_extracted += len(key_paras)

    print(f"Extracted {total_extracted} key paragraphs from {len(jsonl_files)} sessions")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for month in sorted(sessions_by_month.keys()):
        sessions = sessions_by_month[month]
        filepath = OUTPUT_DIR / f"{month}-archive.md"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# Session Archive: {month}\n\n")
            f.write(f"generated: {datetime.now().isoformat()}\n")
            f.write(f"sessions: {len(sessions)}\n")
            f.write(f"key_paragraphs_total: {sum(len(s['key_paras']) for s in sessions)}\n\n")
            f.write("---\n\n")
            f.write("## Search guide\n\n")
            f.write("grep patterns:\n")
            f.write('  keyword search:  grep -n "CatBoost\\|hit@1\\|設計" document/sessions/*.md\n')
            f.write("  by session id:   grep -n 'session_id.*<uuid>' document/sessions/*.md\n")
            f.write("  by date:         grep -n '^### 2026-05-25' document/sessions/*.md\n\n")
            f.write("---\n\n")

            for s in sorted(sessions, key=lambda x: x["date"]):
                block = format_session_block(
                    s["id"], s["title"], s["date"],
                    s["user_msgs"], s["key_paras"]
                )
                f.write(block)
                f.write("\n---\n\n")

        print(f"[OK] {filepath.name} ({len(sessions)} sessions, "
              f"{sum(len(s['key_paras']) for s in sessions)} paragraphs)")

    print(f"\n[OK] Archives saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
