# 蒲田1・蒲田7 セクション別角番EDA 実装計画

**作成日**: 2026-06-13
**実装担当**: Codex
**プランニング**: Claude

## 背景・目的

`ml/analysis/kamata_corner_mirror_analysis.py` で蒲田1・蒲田7の角番（kakuban）と
`residual_diff`（機種内偏差化した差枚）の相関を全台合算で計算した結果、相関は
非常に弱い（蒲田1: -0.02〜+0.03、蒲田7: -0.02〜+0.05）。

これはみとや大森町店のEDAで得られた知見と整合する：
**全島・全セクション合算では角番効果が希釈される**。みとやでは島別に分割した
ところ main_jug（メインジャグラー島）でのみ角番効果が明確（Kruskal-Wallis ε²=0.0067）、
バラエティ島はε²=0で角番効果なしと判定された。

蒲田1・蒲田7でも同様に、**セクション別／島タイプ別に分割**して角番効果の
有無を検証する。

## 使用データ（既存のものを再利用）

- `ml/analysis/results/kamata_corner_mirror/kamata1_machine_frame_all.csv`
- `ml/analysis/results/kamata_corner_mirror/kamata7_machine_frame_all.csv`
- `ml/analysis/results/kamata_corner_mirror/kamata_corner_mirror_kakuban_kamata1_2F.csv`
- `ml/analysis/results/kamata_corner_mirror/kamata_corner_mirror_kakuban_kamata7_2F.csv`
- `ml/analysis/results/kamata_corner_mirror/kamata_corner_mirror_kakuban_kamata7_3F.csv`

これらには既に `machine_number`, `section`, `X`, `Y`, `kakuban`,
`residual_diff`, `residual_games`, `mean_games` が台×期間粒度で含まれている
（実カラムを確認済み）。machine_master の `jug_flag` / `hana_flag` / `bt_flag` /
`machine_type_segment`（前セッションで `kamata_corner_mirror_analysis.py` に
追加済み）が `machine_frame_*.csv` 側に存在するか確認し、なければ同様にJOINして
追加する。

## 分析ステップ

### ステップ1: セクション別 Kruskal-Wallis ε²

各ホール・各フロアについて、セクションごとに
`kakuban`（カテゴリ変数として扱う）と `residual_diff` の
Kruskal-Wallis ε² を計算する。

```python
from scipy.stats import kruskal

def epsilon_squared(df, group_col, value_col):
    groups = [g[value_col].dropna().values for _, g in df.groupby(group_col)]
    groups = [g for g in groups if len(g) > 0]
    if len(groups) < 2:
        return float("nan")
    h_stat, _ = kruskal(*groups)
    n = sum(len(g) for g in groups)
    k = len(groups)
    return (h_stat - k + 1) / (n - k)
```

- セクションごとに台数（n_machines）・行数（n_rows）・ε²・
  角番1〜末尾の `residual_diff` 平均勾配（rank1 - rank_max）を出力。
- セクションの台数が少なすぎる（n_machines < 6 程度）場合は
  ε²が不安定になるため `low_sample` フラグを立てる。

### ステップ2: 機種タイプ別（島タイプ別）集約

みとやの `main_jug` / `main_mix` / `bari` 分類に相当する区分を、
`machine_type_segment`（jug_flag/hana_flag→"A"、bt_flag→別区分、
それ以外→"other" など、既存ロジックを再利用）で行う。

- `machine_type_segment` × セクション、または `machine_type_segment` 単独で
  ステップ1と同じε²計算を行う。
- ε² > 0.005 程度のセクション/タイプを「角番効果あり候補」、
  ε² ≈ 0 を「角番効果なし（除外候補）」として一覧化する。

### ステップ3: 3カテゴリ化での再検証

ε²が小さく見えたセクションについて、二値（角番1 vs 末尾）ではなく
3カテゴリ（角番1=通路側 / 中間 / 末尾=奥側）に分けて
`residual_diff` の平均を比較する（みとやで「二値だと中間情報が消える」
という落とし穴があったため）。

```python
df["kakuban_cat3"] = np.select(
    [df["kakuban"] == 1, df["kakuban"] == df.groupby("section")["kakuban"].transform("max")],
    ["near", "far"],
    default="mid",
)
```

### ステップ4: 機種固定配置の交絡チェック

ステップ1/2でε²が高かったセクションについて、
そのセクション内で「特定の角番に長期間（100日以上）固定配置されている
機種があるか」を確認する。

```sql
SELECT machine_number, machine_name,
       COUNT(DISTINCT date) AS n_days,
       AVG(diff_coins_normalized) AS avg_diff
FROM machine_detailed_results
WHERE machine_number BETWEEN <section_min> AND <section_max>
GROUP BY machine_number, machine_name
ORDER BY machine_number, MIN(date);
```

機種が長期固定されている台が角番効果の高い角番に集中していないか確認し、
「角番効果」と「機種固定配置効果」を区別する。

## 出力

- `kamata_section_kakuban_epsilon_<hall>_<floor>.csv`
  （section, n_machines, n_rows, epsilon_sq, gradient, low_sample）
- `kamata_segment_kakuban_epsilon_<hall>_<floor>.csv`
  （machine_type_segment, epsilon_sq, gradient）
- `kamata_section_kakuban_cat3_<hall>_<floor>.csv`
  （section, kakuban_cat3, mean_residual_diff, n）
- コンソール: ε²降順でトップ5セクション／タイプのサマリー出力

## 発展系（次フェーズ、本計画では着手しない）

みとやのinstinct `mitoya-island-date-group-regression-confirms-real-signal-exists`
で「個体×二値分類はAUC≈0.5でもセクション/島×日の集団×連続値regression
（over_104_rate等）に粒度転換すると有意な信号（Pearson 0.26〜0.48）が
出た」ことが実証されている。

ステップ1〜4で「角番効果あり」と判定されたセクション／タイプが見つかった場合、
それを使って **セクション×日 の集団regression**（目的変数: そのセクションの
その日のプラス率や平均差枚）を蒲田1・蒲田7で試し、みとやと同じ粒度転換効果が
再現するか検証する。これは「みとや固有の現象」か「パチンコ予測一般の原則」かを
切り分ける重要な検証になる。

ただし本フェーズではまず**角番効果がそもそも存在するセクション/タイプを
特定すること**を優先する。効果が見つからなければ粒度転換の対象自体が
存在しないため、ステップ1〜4の結果を見てから着手判断する。
