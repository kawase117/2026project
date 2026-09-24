# 死亡検知ステータス

recent 窓: 直近 180 日 / baseline: それ以前の全期間 / CI: 7日ブロックブートストラップ

検定しているのは「効果がゼロか」ではなく **「過去水準から変わったか」**。
`UNDERPOWERED` は「変わっていない」ではなく **「変化を見分けられない」** の意味。
差枚は使っていない（回転数の混入を避けるため。FINDINGS 追試8）。

## アラート: 10 件

- **WEAKENED** `mitoya_jug_corner1` / payout: +2.940 → +1.175 pp (差 -1.765, CI [-2.417, -1.035])
- **WEAKENED** `mitoya_jug_corner1` / rb_rate: +0.371 → +0.079 回/1000G (差 -0.292, CI [-0.373, -0.206])
- **WEAKENED** `mitoya_jug_corner1` / bonus_rate: +0.563 → +0.199 回/1000G (差 -0.364, CI [-0.480, -0.233])
- **WEAKENED** `rakuen_bt_edge1` / payout: +1.375 → +0.644 pp (差 -0.731, CI [-1.344, -0.096])
- **DEAD** `rakuen_jug_edge1` / rb_rate: +0.072 → +0.013 回/1000G (差 -0.059, CI [-0.104, -0.014])
- **DEAD** `rakuen_clean_edge1_bt` / payout: +1.589 → +0.292 pp (差 -1.297, CI [-2.203, -0.580])
- **WEAKENED** `rakuen_clean_edge1_bt` / bonus_rate: +0.218 → +0.100 回/1000G (差 -0.119, CI [-0.217, -0.032])
- **WEAKENED** `mitoya_jug_edge1` / payout: +1.999 → +0.922 pp (差 -1.078, CI [-1.587, -0.574])
- **WEAKENED** `mitoya_jug_edge1` / rb_rate: +0.208 → +0.070 回/1000G (差 -0.139, CI [-0.198, -0.075])
- **WEAKENED** `mitoya_jug_edge1` / bonus_rate: +0.364 → +0.158 回/1000G (差 -0.206, CI [-0.290, -0.117])

## 全結果

| claim | 指標 | baseline | recent | 差 | 差CI | 検出限界 | 判定 |
|---|---|---|---|---|---|---|---|
| `mitoya_jug_corner1` | payout (pp) | +2.940 [+2.655, +3.195] | +1.175 [+0.572, +1.847] | -1.765 | [-2.417, -1.035] | ±0.691 | **WEAKENED** |
| `mitoya_jug_corner1` | rb_rate (回/1000G) | +0.371 [+0.338, +0.403] | +0.079 [+0.004, +0.159] | -0.292 | [-0.373, -0.206] | ±0.084 | **WEAKENED** |
| `mitoya_jug_corner1` | bonus_rate (回/1000G) | +0.563 [+0.519, +0.602] | +0.199 [+0.091, +0.321] | -0.364 | [-0.480, -0.233] | ±0.123 | **WEAKENED** |
| `k7_jug_kakuban1` | payout (pp) | +0.089 [-0.202, +0.428] | -0.111 [-0.476, +0.222] | -0.200 | [-0.712, +0.233] | ±0.472 | **NO_BASELINE** |
| `k7_jug_kakuban1` | rb_rate (回/1000G) | -0.041 [-0.070, -0.010] | -0.075 [-0.119, -0.021] | -0.035 | [-0.088, +0.028] | ±0.058 | **UNDERPOWERED** |
| `k7_jug_kakuban1` | bonus_rate (回/1000G) | +0.034 [-0.009, +0.086] | -0.018 [-0.075, +0.041] | -0.052 | [-0.133, +0.021] | ±0.077 | **NO_BASELINE** |
| `k7_at_kakuban1` | payout (pp) | -1.233 [-1.843, -0.472] | -0.908 [-1.841, +0.054] | +0.325 | [-0.898, +1.427] | ±1.162 | **UNDERPOWERED** |
| `rakuen_bt_edge1` | payout (pp) | +1.375 [+0.985, +1.788] | +0.644 [+0.191, +1.150] | -0.731 | [-1.344, -0.096] | ±0.624 | **WEAKENED** |
| `rakuen_bt_edge1` | rb_rate (回/1000G) | +0.054 [+0.030, +0.083] | +0.051 [+0.026, +0.085] | -0.002 | [-0.041, +0.039] | ±0.040 | **UNDERPOWERED** |
| `rakuen_bt_edge1` | bonus_rate (回/1000G) | +0.184 [+0.135, +0.239] | +0.144 [+0.106, +0.201] | -0.040 | [-0.104, +0.038] | ±0.071 | **ALIVE** |
| `rakuen_jug_edge1` | payout (pp) | +0.739 [+0.474, +0.995] | +0.588 [+0.205, +0.952] | -0.151 | [-0.612, +0.296] | ±0.454 | **UNDERPOWERED** |
| `rakuen_jug_edge1` | rb_rate (回/1000G) | +0.072 [+0.045, +0.095] | +0.013 [-0.027, +0.049] | -0.059 | [-0.104, -0.014] | ±0.045 | **DEAD** |
| `rakuen_jug_edge1` | bonus_rate (回/1000G) | +0.148 [+0.105, +0.187] | +0.099 [+0.041, +0.156] | -0.048 | [-0.118, +0.022] | ±0.070 | **ALIVE** |
| `rakuen_hana_edge1` | payout (pp) | +1.317 [+0.668, +1.943] | +0.186 [-0.940, +1.192] | -1.131 | [-2.417, +0.022] | ±1.220 | **UNDERPOWERED** |
| `rakuen_hana_edge1` | rb_rate (回/1000G) | +0.123 [+0.060, +0.177] | +0.074 [-0.013, +0.171] | -0.049 | [-0.150, +0.070] | ±0.110 | **UNDERPOWERED** |
| `rakuen_hana_edge1` | bonus_rate (回/1000G) | +0.269 [+0.179, +0.356] | +0.114 [-0.037, +0.257] | -0.156 | [-0.329, +0.013] | ±0.171 | **UNDERPOWERED** |
| `rakuen_clean_edge1_jug` | payout (pp) | +1.278 [+0.933, +1.621] | +0.963 [+0.399, +1.479] | -0.315 | [-0.978, +0.308] | ±0.643 | **UNDERPOWERED** |
| `rakuen_clean_edge1_jug` | rb_rate (回/1000G) | +0.100 [+0.066, +0.131] | +0.050 [-0.003, +0.102] | -0.050 | [-0.111, +0.013] | ±0.062 | **UNDERPOWERED** |
| `rakuen_clean_edge1_jug` | bonus_rate (回/1000G) | +0.226 [+0.175, +0.276] | +0.178 [+0.086, +0.263] | -0.048 | [-0.154, +0.052] | ±0.103 | **ALIVE** |
| `rakuen_clean_edge1_bt` | payout (pp) | +1.589 [+1.172, +2.074] | +0.292 [-0.450, +0.888] | -1.297 | [-2.203, -0.580] | ±0.811 | **DEAD** |
| `rakuen_clean_edge1_bt` | rb_rate (回/1000G) | +0.067 [+0.040, +0.101] | +0.041 [+0.013, +0.073] | -0.026 | [-0.071, +0.017] | ±0.044 | **UNDERPOWERED** |
| `rakuen_clean_edge1_bt` | bonus_rate (回/1000G) | +0.218 [+0.163, +0.284] | +0.100 [+0.027, +0.165] | -0.119 | [-0.217, -0.032] | ±0.092 | **WEAKENED** |
| `rakuen_dd_jug` | payout (pp) | +2.262 [+1.762, +2.719] | +2.265 [+1.398, +3.037] | +0.003 | [-0.986, +0.926] | ±0.956 | **ALIVE** |
| `rakuen_dd_jug` | rb_rate (回/1000G) | +0.270 [+0.213, +0.322] | +0.346 [+0.255, +0.434] | +0.076 | [-0.030, +0.182] | ±0.106 | **ALIVE** |
| `rakuen_dd_jug` | bonus_rate (回/1000G) | +0.421 [+0.331, +0.503] | +0.476 [+0.324, +0.615] | +0.056 | [-0.119, +0.222] | ±0.170 | **ALIVE** |
| `rakuen_dd_hana` | payout (pp) | +6.408 [+5.176, +7.576] | +6.940 [+5.318, +8.685] | +0.532 | [-1.477, +2.711] | ±2.094 | **ALIVE** |
| `rakuen_dd_hana` | rb_rate (回/1000G) | +0.453 [+0.366, +0.535] | +0.469 [+0.354, +0.596] | +0.016 | [-0.125, +0.175] | ±0.150 | **ALIVE** |
| `rakuen_dd_hana` | bonus_rate (回/1000G) | +0.979 [+0.806, +1.140] | +1.029 [+0.807, +1.277] | +0.050 | [-0.225, +0.363] | ±0.294 | **ALIVE** |
| `rakuen_dd_bt` | payout (pp) | +2.488 [+1.797, +3.157] | +2.755 [+1.841, +3.648] | +0.268 | [-0.862, +1.401] | ±1.131 | **ALIVE** |
| `rakuen_dd_bt` | rb_rate (回/1000G) | +0.092 [+0.055, +0.130] | +0.119 [+0.068, +0.169] | +0.027 | [-0.037, +0.089] | ±0.063 | **UNDERPOWERED** |
| `rakuen_dd_bt` | bonus_rate (回/1000G) | +0.288 [+0.200, +0.375] | +0.334 [+0.226, +0.442] | +0.045 | [-0.093, +0.186] | ±0.139 | **ALIVE** |
| `rakuen_dd_at` | payout (pp) | +2.185 [+1.579, +2.771] | +1.624 [+0.891, +2.326] | -0.561 | [-1.486, +0.382] | ±0.934 | **ALIVE** |
| `k1_jug_edge1` | payout (pp) | +0.119 [-0.120, +0.306] | +0.026 [-0.342, +0.355] | -0.093 | [-0.488, +0.324] | ±0.406 | **NO_BASELINE** |
| `k1_jug_edge1` | rb_rate (回/1000G) | -0.002 [-0.030, +0.023] | +0.032 [+0.000, +0.066] | +0.034 | [-0.005, +0.079] | ±0.042 | **NO_BASELINE** |
| `k1_jug_edge1` | bonus_rate (回/1000G) | +0.045 [+0.000, +0.081] | +0.020 [-0.079, +0.099] | -0.024 | [-0.126, +0.068] | ±0.097 | **UNDERPOWERED** |
| `mitoya_jug_edge1` | payout (pp) | +1.999 [+1.774, +2.231] | +0.922 [+0.471, +1.374] | -1.078 | [-1.587, -0.574] | ±0.507 | **WEAKENED** |
| `mitoya_jug_edge1` | rb_rate (回/1000G) | +0.208 [+0.183, +0.230] | +0.070 [+0.013, +0.128] | -0.139 | [-0.198, -0.075] | ±0.062 | **WEAKENED** |
| `mitoya_jug_edge1` | bonus_rate (回/1000G) | +0.364 [+0.329, +0.397] | +0.158 [+0.079, +0.239] | -0.206 | [-0.290, -0.117] | ±0.086 | **WEAKENED** |

## 監視対象の由来

- `mitoya_jug_corner1` — document/mitoya_theory.md §2.1 h_jug corner1　※陽性対照。2026-04-27 に消失済みと判定されている（追試6・追試7）。この仕組みが DEAD を出せなければ検知器として使えない
- `k7_jug_kakuban1` — document/kamata7_theory.md §2.1a　※陰性対照。追試8・追試9で設定差なしと判定済み。NO_BASELINE が出るのが正しい
- `k7_at_kakuban1` — backtest/results/regime/FINDINGS.md 追試2（AT一般 -1.205pp）　※AT機は bb_count/rb_count が意味を持たないため payout のみ。追試8の回転数分解は未実施の主張
- `rakuen_bt_edge1` — document/rakuen_theory.md §2.1b（技術介入 +1.127pp）　※2026-07-06 に島配列の工事あり。machine_layout_history の日付次元で工事前後それぞれ正しい位置が当たるので、期間の打ち切りは不要になった（旧: date_max=20260705）
- `rakuen_jug_edge1` — document/rakuen_theory.md §2.1b（ジャグ +0.349pp）　※旧§2.1bの端番定義。§2.1cで rakuen_clean_edge1_jug に置き換わったが旧定義の生死も追う。date_max=20260705 は machine_layout_history 導入前の暫定措置なので撤去（load_frame が日付結合するようになった）
- `rakuen_hana_edge1` — document/rakuen_theory.md §2.1b（ハナハナ +0.869pp）　※旧§2.1bの端番定義。date_max=20260705 は machine_layout_history 導入前の暫定措置なので撤去
- `rakuen_clean_edge1_jug` — document/rakuen_theory.md §2.1c / registry rk-clean-edge1-jug（ジャグ +1.207pp [+0.784,+1.638]、6期中6期有意）　※現行の端番定義。frame/interior_split/special を除いた clean 列の depth=1。工事前後の両エポックで成立とされているため期間は打ち切らない。⚠️ 2026-07-28に registry rk-clean-edge1-jug で失効判定済み（HYPOTHESIS_LEDGER.md、死亡日特定不能な緩やかな減衰）。運用中の推薦ルールでは既に使っていない。mitoya_jug_corner1と同じく、検知器がこの既知の失効を正しく出し続けられるかの陽性対照として維持する
- `rakuen_clean_edge1_bt` — document/rakuen_theory.md §2.1c / registry rk-clean-edge1-bt（技術介入 +1.403pp [+0.914,+1.826]、6期中5期有意）　※§2.1c は jug/hana を先に取る排他カテゴリで測っているので universe も同じ優先順で切る。⚠️ 2026-07-28に registry rk-clean-edge1-bt で失効判定済み（HYPOTHESIS_LEDGER.md、死亡: 2026年5〜6月に明確な崩壊）。運用中の推薦ルールでは既に使っていない。陽性対照として維持する
- `rakuen_dd_jug` — document/rakuen_theory.md §3.1a / registry rk-event-dd-jug（イベントDD {22,5,11,25,15}）　※日付軸。同日対比が作れないので cross_day（機種構成調整済みの日次水準を、対象日 vs 対照日で比較）
- `rakuen_dd_hana` — document/rakuen_theory.md §3.1a / registry rk-event-dd-hana（イベントDD {7,17,27}）　※全カテゴリ中で最も日差が大きい。位置軸は検定不能（外周配置）なので、このホールのハナハナはこの claim が唯一の監視対象
- `rakuen_dd_bt` — document/rakuen_theory.md §3.1a / registry rk-event-dd-bt（イベントDD {30,22,11}）
- `rakuen_dd_at` — document/rakuen_theory.md §3.1a / registry rk-event-dd-at（イベントDD {30,22,11,10}）　※AT機は bb_count/rb_count が概念的に対応しないため payout のみ
- `k1_jug_edge1` — backtest/results/regime/FINDINGS.md 追試3（蒲田1 +0.068pp、プールでは検出されず）　※蒲田1は rank_from_aisle が全NULLのためセクション端で代用。追試3ではプール平均で null
- `mitoya_jug_edge1` — backtest/results/regime/FINDINGS.md 追試3（みとや +1.575pp）　※通路角番とは別軸。角番1の死亡がセクション端にも及んでいるかを見る
