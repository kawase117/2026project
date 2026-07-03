---
name: instinct-import
description: document/instincts/配下のYAML洞察を読み込み、ドメイン別に表示・検索する。新セッション開始時や過去の知見を参照したい時に使用。書き込みはinstinct-exportを使うこと。
---

# Instinct Import (Local YAML)

Loads project insights from `document/instincts/` YAML files and displays them for reference in the current session.

## Usage

```
/instinct-import                    # Load all insights
/instinct-import <domain>           # Load insights for specific domain
/instinct-import --list             # List all available insights by domain
/instinct-import --search <keyword> # Search insights by keyword or id
```

## What It Does

1. Scans `document/instincts/` for all YAML files
2. Parses each insight object (id, trigger, confidence, domain, background, action, examples)
3. Displays insights grouped by domain
4. Shows confidence levels and trigger conditions for context

## Output Format (Display)

```
==========================================
  LOADED INSIGHTS (5 total)
==========================================

### ML-FEATURE-ENGINEERING (3)
  ✓ tree-models-need-feature-engineering [0.90]
    Trigger: when implementing tree-based ML models
    Action: XGBoost needs composite features for 5%+ AUC improvement
  
  ✓ target-encoding-dimension-reduction [0.85]
    Trigger: when dealing with high-cardinality categorical features
    Action: Target encoding reduces 3100+ → 10 dimensions while preserving signal

### ML-HYPERPARAMETER-TUNING (1)
  ✓ shallow-trees-prevent-overfitting [0.80]
    Trigger: when training tree-based models on moderate-sized datasets
    Action: Use max_depth=3, learning_rate=0.01 to prevent overfitting

### ML-PROJECT-PLANNING (1)
  ✓ realistic-ml-improvement-targets [0.75]
    Trigger: when setting AUC improvement goals
    Action: Phase 6B realistic target: 0.56-0.58 (not 0.65)
```

## Files Read

- **Source**: `document/instincts/` (all YAML files with `.yaml` extension)
- **Format**: YAML with insight blocks separated by `---`
- **Fields**: フィールド定義は `~/.claude/skills/instinct-export/references/schema.md` を参照(instinct-exportと共通の契約)

---

**Implementation**: This skill reads all YAML files from the instincts folder, parses insights, and displays them grouped by domain with confidence levels. Enables knowledge transfer across sessions without re-deriving patterns.
