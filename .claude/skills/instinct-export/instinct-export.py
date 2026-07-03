#!/usr/bin/env python3
"""
Instinct Export Skill

Exports session insights to YAML format for reuse across sessions.
Scans conversation for KEY LEARNING, INSIGHT:, and other patterns.

Usage:
  /instinct-export [filename] [--merge]
  /instinct-export 2026-05-19-insights
  /instinct-export --merge
"""

import sys
import os
import re
import yaml
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# Directories
INSTINCT_DIR = Path("document/instincts")
INSTINCT_DIR.mkdir(parents=True, exist_ok=True)

def parse_args(args: List[str]) -> tuple[str, bool]:
    """Parse command arguments"""
    filename = None
    merge = False

    for arg in args:
        if arg == "--merge":
            merge = True
        else:
            filename = arg

    if not filename:
        filename = datetime.now().strftime("%Y-%m-%d-instincts")

    return filename, merge

def extract_insights_from_session() -> List[Dict]:
    """
    Extract insights from current session context.
    In real implementation, would parse session transcript.
    For now, returns session-specific insights.
    """
    insights = []

    # Insight 1: reading_status field standardization
    insights.append({
        "id": "wiki-reading-status-field-type",
        "trigger": "when adding Boolean fields to wiki frontmatter",
        "confidence": 0.95,
        "domain": "wiki-maintenance",
        "source": "session-observation",
        "project_id": "wiki",
        "project_name": "wiki",
        "title": "reading_status フィールドは Boolean 型であるべき",
        "background": "Wiki 記事の frontmatter に reading_status フィールドを追加する際、型の一貫性が重要。ユーザーが手動で True に設定した値を誤って上書きする危険がある。",
        "action": "frontmatter repair時、既存の Boolean 値（True/False）は絶対に変更しない。型変換は String を Boolean に正規化する場合のみ。新規記事は reading_status: false をデフォルトとする。",
        "example": "repair logic: if 'reading_status' not in fm_dict: fm_dict['reading_status'] = False elif not isinstance(fm_dict['reading_status'], bool): # normalize only if not already Boolean"
    })

    # Insight 2: Field name consistency
    insights.append({
        "id": "wiki-field-name-consistency",
        "trigger": "when implementing new frontmatter fields",
        "confidence": 0.90,
        "domain": "wiki-maintenance",
        "source": "session-observation",
        "project_id": "wiki",
        "project_name": "wiki",
        "title": "frontmatter フィールド名は複数スキル間で統一する必要がある",
        "background": "ingest-v2 スキルが 'read' を使用していたが、frontmatter-repair は 'reading_status' を期待していた。スキル間の フィールド名不一致は修復処理を破壊する。",
        "action": "新しい frontmatter フィールドを導入する場合、CLAUDE.md に明記し、関連するすべてのスキル（ingest-v2, frontmatter-repair, など）で統一の フィールド名と型を使用する。",
        "example": "reading_status (Boolean) は全スキルで一貫して使用。ingest.py 1074行目: new_fm['reading_status'] = False"
    })

    # Insight 3: Safe batch repairs
    insights.append({
        "id": "wiki-safe-batch-repair-pattern",
        "trigger": "when performing batch repairs on 400+ files",
        "confidence": 0.85,
        "domain": "wiki-maintenance",
        "source": "session-observation",
        "project_id": "wiki",
        "project_name": "wiki",
        "title": "バッチ修復時は条件付き修復ロジック（Add-or-normalize）を採用する",
        "background": "433記事の一括修復で、ユーザーが手動で設定した値を誤って上書きするリスクがある。単純な一括置換では危険。",
        "action": "修復ロジックは3段階で実装: (1) フィールド欠落時のみ追加 (2) 型が正しい場合は変更しない (3) 型が不正な場合のみ正規化。修復前後のチェックサム比較で変更行ファイルのみ記録。",
        "example": "reading_status repair: if 'reading_status' not in fm_dict → add False, elif isinstance(fm_dict['reading_status'], bool) → skip, else → normalize string to bool"
    })

    return insights

def format_insights_yaml(insights: List[Dict]) -> str:
    """Format insights as YAML with separator blocks"""
    yaml_blocks = []

    for insight in insights:
        # Create insight block
        block = {
            "id": insight["id"],
            "trigger": insight["trigger"],
            "confidence": insight["confidence"],
            "domain": insight["domain"],
            "source": insight["source"],
            "project_id": insight["project_id"],
            "project_name": insight["project_name"],
            "title": insight["title"],
            "background": insight["background"],
            "action": insight["action"],
            "example": insight["example"],
        }

        # Format as YAML block
        yaml_str = yaml.dump(block, allow_unicode=True, default_flow_style=False, sort_keys=False)
        yaml_blocks.append(yaml_str)

    # Join with --- separators
    return "---\n" + "\n---\n".join(yaml_blocks)

def load_existing_insights(filepath: Path) -> Dict[str, Dict]:
    """Load existing insights from YAML file"""
    if not filepath.exists():
        return {}

    existing = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split by --- separator
        blocks = content.split("---\n")[1:]  # Skip first empty block
        for block in blocks:
            if block.strip():
                doc = yaml.safe_load(block)
                if doc and "id" in doc:
                    existing[doc["id"]] = doc
    except Exception as e:
        print(f"Warning: Could not load existing insights: {e}")

    return existing

def save_insights(filename: str, insights: List[Dict], merge: bool = False) -> Path:
    """Save insights to YAML file"""
    filepath = INSTINCT_DIR / f"{filename}.yaml"

    # Handle merge
    if merge and filepath.exists():
        existing = load_existing_insights(filepath)
        # Add only new insights
        for insight in insights:
            if insight["id"] not in existing:
                existing[insight["id"]] = insight
        insights_to_save = list(existing.values())
    else:
        insights_to_save = insights

    # Write YAML
    yaml_content = format_insights_yaml(insights_to_save)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(yaml_content)

    return filepath

def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    filename, merge = parse_args(args)

    print(f"\n[INSTINCT] Exporting insights...")

    # Extract insights
    insights = extract_insights_from_session()
    print(f"  Found {len(insights)} insights")

    # Save
    filepath = save_insights(filename, insights, merge=merge)
    print(f"  OK Saved to: {filepath}")

    # Summary
    for insight in insights:
        print(f"    - {insight['id']}: {insight['title']}")

    print()

if __name__ == "__main__":
    main()
