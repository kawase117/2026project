---
name: instinct-export
description: 現在セッションの洞察をdocument/instincts/にYAML形式でエクスポートする。重要な発見・パターンを次セッション以降に持ち越したい時、セッション終盤に使用。読み込みはinstinct-importを使うこと。
---

# Instinct Export Skill

Exports session insights to YAML format for reuse across future sessions.

## Usage

```
/instinct-export [filename] [--merge]
```

### Examples

```
/instinct-export 2026-05-19-frontmatter-repair-insights
/instinct-export                                # Defaults to YYYY-MM-DD-instincts.yaml
/instinct-export 2026-05-19 --merge            # Merge with existing insights
```

## What It Does

1. Extracts insights from the current session
2. Formats each as a YAML insight object with:
   - `id`: unique identifier (kebab-case)
   - `trigger`: when this insight applies
   - `confidence`: 0.0-1.0 confidence score
   - `domain`: insight category
   - `source`: how the insight was acquired
   - `project_id` / `project_name`: project context
   - `title`: insight title
   - `background`: motivation/context
   - `action`: what to do when trigger occurs
   - `example`: code or scenario demonstrating the insight

3. Writes to `document/instincts/<filename>.yaml`
4. Optionally merges with existing insights (with duplicate detection)

## Output Format

YAMLスキーマの全フィールド定義は `references/schema.md` を参照(instinct-importと共通の契約)。

## Files

- **Skill**: `instinct-export.py`
- **Output**: `document/instincts/<filename>.yaml`

## Implementation

- Parses session context for insights
- Formats as YAML with `---` block separators
- Supports merge mode (deduplication by `id`)
- Error handling for malformed YAML

---

**Created**: 2026-05-19  
**Status**: ✅ Ready for use
