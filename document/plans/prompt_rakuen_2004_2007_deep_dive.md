# Codex Prompt: 楽園蒲田店 2004-2007 セクション深掘り分析

## 目的

セクション横展開検証で「60日中52日がTop1セクション」だった楽園・新館2F・2004-2007（4台）を深掘りする。
セクション全体だけでなく、**台番号ごとの個別パフォーマンス**も分析し、この強さがどの条件下で発生するか特定する。

## ゴール

**新規スクリプト `eda/rakuen_2004_2007_deep_dive.py` を作成**し、以下を出力する:
1. DD別（日付の日: 1-31）の成績サマリー
2. 曜日別の成績サマリー
3. 月別の平均G数・平均差枚・勝率
4. 台番号別（2004/2005/2006/2007 個別）の上記すべて
5. 統合レポート (`eda/results/rakuen_2004_2007/report.md`)

## データソース

- DB: `db/楽園蒲田店.db`
- テーブル: `machine_detailed_results`
- 対象台番号: 2004, 2005, 2006, 2007
- 全期間: 20250101〜20260628（542日）
- hall_name 列は DB に存在しない。SELECT しないこと

### 機種変遷（4台共通）
| 期間 | 機種 | 日数 |
|------|------|------|
| 2025-01-01〜2025-02-03 | マクロスフロンティア4 | 34 |
| 2025-02-04〜2025-05-06 | にゃんこ大戦争 超神速 | 91 |
| 2025-05-07〜2025-09-07 | 機動戦士ガンダムSEED | 124 |
| 2025-09-08〜2025-10-05 | デビル メイ クライ5 | 28 |
| 2025-10-06〜2025-12-22 | いざ！番長 / 吉宗 | 78 |
| 2025-12-23〜2026-06-28 | HEY！エリートサラリーマン鏡 | 187 |

※ 2004 のみ「いざ！番長」、2005-2007 は「吉宗」。その他は4台同一。

### 列の定義
```sql
SELECT date, machine_number, machine_name,
       games_normalized, diff_coins_normalized
FROM machine_detailed_results
WHERE machine_number BETWEEN 2004 AND 2007
```

- `date`: TEXT型、YYYYMMDD形式
- `games_normalized`: INTEGER（回転数）
- `diff_coins_normalized`: INTEGER（差枚数。正=勝ち、負=負け）

### 前処理フィルタ
```python
# games_normalized == 0 が302行（14%）存在する。ゼロ除算を防ぐため除外する
df = df[df["games_normalized"] > 0].copy()
```

### 派生指標の計算
```python
payout_rate = ((games_normalized * 3 + diff_coins_normalized) / (games_normalized * 3)) * 100
# ※ 全台 N 分類（AT/ART系）なので hit_threshold = 106.0 を使う
hit_flag = payout_rate >= 106.0
win_flag = diff_coins_normalized > 0  # 勝率用
```

**注意**: `classify_seg` を使うとこの4台は全て "N" を返す。hit_flag 計算の閾値は固定で 106.0 でよい。
勝率（win_flag）は差枚 > 0 で単純判定。payout_rate ベースの hit_flag とは別の指標。

## 分析軸

### 1. DD別分析（日付の日: 1-31）
```python
dd = pd.to_datetime(date, format='%Y%m%d').day
```

出力テーブル（セクション全体 + 台番号別）:
| dd | n_days | avg_games | avg_diff | win_rate | hit_rate | avg_payout_rate |

- n_days: そのDDが出現した日数（4台×n日ではなく、カレンダー上の日数）
- avg_games: 4台平均の games_normalized
- avg_diff: 4台平均の diff_coins_normalized
- win_rate: diff_coins_normalized > 0 の割合
- hit_rate: payout_rate >= 106.0 の割合
- avg_payout_rate: 4台平均のpayout_rate

楽園の EVENT_DDS = {1, 4, 7, 14, 17, 24, 27, 30}（仮定義）。このDDがevent_ddsに含まれるかのフラグも付与して、イベント日 vs 非イベント日の比較テーブルも出力。

### 2. 曜日別分析
```python
dow = pd.to_datetime(date, format='%Y%m%d').dayofweek  # 0=月, 6=日
dow_label = ['月','火','水','木','金','土','日'][dow]
```

出力テーブル（セクション全体 + 台番号別）:
| dow | dow_label | n_days | avg_games | avg_diff | win_rate | hit_rate | avg_payout_rate |

### 3. 月別分析
```python
year_month = date[:6]  # "202501" 形式
```

出力テーブル（セクション全体 + 台番号別）:
| year_month | machine_name_primary | n_days | avg_games | avg_diff | win_rate | hit_rate | avg_payout_rate |

- machine_name_primary: その月で最も出現日数が多い機種名。同数の場合は日付が早い方（最初に出現した機種名）を採用する

### 4. 台番号別の個別分析
上記1-3のすべてを、セクション全体（4台合算）に加えて台番号 2004/2005/2006/2007 ごとに個別に出力する。

出力テーブルには `scope` 列を追加:
- `scope = "section"` → 4台合算
- `scope = "2004"` → 台番号2004のみ
- `scope = "2005"` → 台番号2005のみ
- `scope = "2006"` → 台番号2006のみ
- `scope = "2007"` → 台番号2007のみ

### 5. 追加比較: 新館2F 全体 vs 2004-2007
2004-2007 の強さが新館2F全体の傾向なのか、このセクションだけなのかを確認する。

新館2F の全台番号を座標CSVから取得:
```python
coords = pd.read_csv(PROJECT_ROOT / "Heatmap" / "shinkan2F_floor_coordinates_rakuen.csv")
shinkan2f_machines = coords["machine_number"].tolist()
# 91台（7セクション）、うちDB存在89台。2004-2007の4台を除いた85台が "other"
```

出力テーブル:
| group | n_machines | n_days | avg_games | avg_diff | win_rate | hit_rate | avg_payout_rate |

- group = "2004-2007"（4台） vs "shinkan2F_other"（85台） vs "shinkan2F_all"（89台）
- n_machines は DB に実データがある台数を使う（座標CSV上の台数ではない）
- hit_threshold は全台 106.0 で統一（新館2Fも N 分類が大半）

## 出力仕様

### ディレクトリ
`eda/results/rakuen_2004_2007/`

### CSV出力

**1. dd_analysis.csv**
列: scope, dd, is_event_dd, n_days, avg_games, avg_diff, win_rate, hit_rate, avg_payout_rate

**2. dow_analysis.csv**
列: scope, dow, dow_label, n_days, avg_games, avg_diff, win_rate, hit_rate, avg_payout_rate

**3. monthly_analysis.csv**
列: scope, year_month, machine_name_primary, n_days, avg_games, avg_diff, win_rate, hit_rate, avg_payout_rate

**4. shinkan2f_comparison.csv**
列: group, n_machines, n_days, avg_games, avg_diff, win_rate, hit_rate, avg_payout_rate

### レポート (report.md)

```markdown
# 楽園蒲田店 2004-2007 セクション深掘り分析

## 1. 概要
- 対象: 新館2F 台番号 2004-2007（4台）
- 期間: 2025-01-01 〜 2026-06-28（542日）
- 全期間平均: G数=XXX, 差枚=XXX, 勝率=XX.X%, hit_rate=XX.X%

## 2. DD別分析（セクション全体）
(dd_analysis.csv の scope="section" をテーブル表示)
- 強いDD Top5 / 弱いDD Top5（hit_rate順）
- イベントDD vs 非イベントDD 比較

## 3. 曜日別分析（セクション全体）
(dow_analysis.csv の scope="section" をテーブル表示)
- 最強曜日 / 最弱曜日

## 4. 月別推移（セクション全体）
(monthly_analysis.csv の scope="section" をテーブル表示)
- 機種変更タイミングとの対応
- トレンド（改善中/悪化中/安定）

## 5. 台番号別比較
| machine_number | total_days | avg_games | avg_diff | win_rate | hit_rate |
(4台の全期間サマリー)
- 4台間の差は大きいか小さいか

## 6. 台番号別 DD分析
(dd_analysis.csv の scope=2004〜2007 で、各台のDD別 hit_rate テーブル)
- 全台共通で強いDD / 特定台だけ強いDD

## 7. 台番号別 曜日分析
(dow_analysis.csv の scope=2004〜2007 で、各台の曜日別テーブル)

## 8. 新館2F 全体との比較
(shinkan2f_comparison.csv をテーブル表示)
- 2004-2007 だけが突出しているか、新館2F全体が強いか

## 9. 結論
- DD×曜日の最適組み合わせ
- 機種変更の影響度
- 台番号ごとの傾向差
- 実運用への推奨（いつ行くか、どの台を狙うか）
```

## 実装方針

- 既存の `eda/section_lateral_expansion.py` のコードは変更しない。完全に独立した新規スクリプト
- `load_machine_data` は使わない（対象が4台に限定されているため、直接SQLで取得する方が効率的）
- DB接続:
```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
```

## 出力制約

- テーブル出力は `to_markdown()` を使わず、自前の簡易Markdown生成で行う
- 日付は YYYYMMDD 形式
- CSV出力は `encoding="utf-8-sig"`
- avg_games, avg_diff は小数点1位まで。win_rate, hit_rate, avg_payout_rate は小数点1位まで（%表示ではなく 0.0-100.0 の数値）
- 空のDD（2月30日など存在しないDD）は出力しない

## 実行確認

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python eda/rakuen_2004_2007_deep_dive.py
```

1. エラーなく完走すること
2. `eda/results/rakuen_2004_2007/report.md` が生成されること
3. 全CSV（dd_analysis.csv, dow_analysis.csv, monthly_analysis.csv, shinkan2f_comparison.csv）が生成されること
4. scope="section" と scope="2004"〜"2007" の5行が各DDに存在すること
5. n_days の合計が妥当であること（DD=1 なら約18日、曜日なら約77日）
