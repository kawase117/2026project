# Session Archive: 2026-05

generated: 2026-07-04T01:04:03.766928
sessions: 1
key_paragraphs_total: 5

---

## Search guide

grep patterns:
  keyword search:  grep -n "CatBoost\|hit@1\|設計" document/sessions/*.md
  by session id:   grep -n 'session_id.*<uuid>' document/sessions/*.md
  by date:         grep -n '^### 2026-05-25' document/sessions/*.md

---

### 2026-05-28 | Session 0811af90
**session_id**: `0811af90-1c5c-44e3-8e6b-ae04565c9f1c`

**User requests**:
- 現在、ClaudeCodeとCodexを併用してコード制作に取り組んでいます。
- 実際の使い方を教えてください。
- InstinctやSkillが溜まると、コンテキスト枠が圧迫されるという話を見ました。

**Key decisions / changes**:

**代表的な検索パターン:**
| パターン | 用途 |
|---------|------|
| `CatBoost\|GPU\|warm_start` | ML学習パラメータの過去改善 |
| `hit@1\|hit@2\|NDCG\|ECE` | 評価指標の選定理由 |
| `walk-forward\|min-train-days` | バリデーション設計の進化 |
| `segment\|セグメント\|2F\|3F` | グループ化戦略の検証結果 |
| `修正\|バグ\|fix` | 既出バグの修正方法確認 |

**1. アーカイブ生成**
```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python extract_session_summaries.py
```
- 出力: `document/sessions/YYYY-MM-archive.md` を自動生成
- 処理: ~/.claude/projects/ の全JSONL (147個→175個と増加予想) から決定・修正・設計変更を自動抽出
- キーワードマッチ: 決定, 修正, 設計, CatBoost, hit@, NDCG, ECE など

**意思決定を探すとき:**
```bash
# キーワード検索（CatBoost パラメータ, hit@1 改善, 設計変更など）
grep -n "CatBoost\|hit@1\|hit@2\|NDCG\|ECE\|設計" document/sessions/2026-0*.md

**チェックリスト**：
```
✓ walk-forward: n_eval_days >= 10 か？
✓ min-train-days: 「訓練窓の幅」ではなく「開始閾値」として使ってるか？
✓ 不均衡データ（base_rate < 10%）: ECE を第一指標にしてるか？
✓ LTR評価指標：hit@1 + hit@2 + NDCG + lift@1 の4つセットか？
✓ 小サンプル警戒：n < 5 のパターンで主張していないか？
```

**結果ロギング**：JSON形式で記録（実験ごと）
```json
{
  "run_id": "catboost_v2_20260529_143000",
  "model": "CatBoostRanker",
  "results": {
    "hit_at_1": 0.31,
    "hit_at_2": 0.58,
    "ndcg": 0.72
  },
  "runtime_hours": 2.4
}
```

---

