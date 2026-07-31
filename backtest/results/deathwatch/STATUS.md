# 死亡検知ステータス

recent 窓: 直近 180 日 / baseline: それ以前の全期間 / CI: 7日ブロックブートストラップ

検定しているのは「効果がゼロか」ではなく **「過去水準から変わったか」**。
`UNDERPOWERED` は「変わっていない」ではなく **「変化を見分けられない」** の意味。
差枚は使っていない（回転数の混入を避けるため。FINDINGS 追試8）。

## アラート: 7 件

- **WEAKENED** `mitoya_jug_corner1` / payout: +2.947 → +2.018 pp (差 -0.930, CI [-1.615, -0.223])
- **WEAKENED** `mitoya_jug_corner1` / rb_rate: +0.373 → +0.215 回/1000G (差 -0.158, CI [-0.241, -0.070])
- **WEAKENED** `mitoya_jug_corner1` / bonus_rate: +0.565 → +0.378 回/1000G (差 -0.187, CI [-0.303, -0.062])
- **WEAKENED** `rakuen_clean_edge1_jug` / payout: +1.382 → +0.619 pp (差 -0.763, CI [-1.354, -0.028])
- **DEAD** `rakuen_clean_edge1_jug` / rb_rate: +0.107 → +0.030 回/1000G (差 -0.078, CI [-0.127, -0.009])
- **WEAKENED** `rakuen_clean_edge1_jug` / bonus_rate: +0.245 → +0.112 回/1000G (差 -0.133, CI [-0.217, -0.018])
- **WEAKENED** `rakuen_clean_edge1_bt` / bonus_rate: +0.222 → +0.121 回/1000G (差 -0.101, CI [-0.206, -0.004])

## 全結果

| claim | 指標 | baseline | recent | 差 | 差CI | 検出限界 | 判定 |
|---|---|---|---|---|---|---|---|
| `mitoya_jug_corner1` | payout (pp) | +2.947 [+2.643, +3.215] | +2.018 [+1.373, +2.638] | -0.930 | [-1.615, -0.223] | ±0.696 | **WEAKENED** |
| `mitoya_jug_corner1` | rb_rate (回/1000G) | +0.373 [+0.333, +0.404] | +0.215 [+0.138, +0.292] | -0.158 | [-0.241, -0.070] | ±0.085 | **WEAKENED** |
| `mitoya_jug_corner1` | bonus_rate (回/1000G) | +0.565 [+0.515, +0.605] | +0.378 [+0.264, +0.490] | -0.187 | [-0.303, -0.062] | ±0.120 | **WEAKENED** |
| `k7_jug_kakuban1` | payout (pp) | +0.123 [-0.218, +0.511] | -0.071 [-0.443, +0.318] | -0.194 | [-0.735, +0.316] | ±0.525 | **NO_BASELINE** |
| `k7_jug_kakuban1` | rb_rate (回/1000G) | -0.032 [-0.061, +0.003] | -0.084 [-0.128, -0.033] | -0.052 | [-0.109, +0.006] | ±0.058 | **NO_BASELINE** |
| `k7_jug_kakuban1` | bonus_rate (回/1000G) | +0.043 [-0.005, +0.102] | -0.015 [-0.075, +0.050] | -0.058 | [-0.141, +0.022] | ±0.082 | **NO_BASELINE** |
| `k7_at_kakuban1` | payout (pp) | -1.144 [-1.908, -0.220] | -1.582 [-2.317, -0.749] | -0.438 | [-1.610, +0.693] | ±1.151 | **UNDERPOWERED** |
| `rakuen_bt_edge1` | payout (pp) | +1.315 [+0.860, +1.731] | +0.929 [+0.350, +1.405] | -0.386 | [-1.102, +0.266] | ±0.684 | **UNDERPOWERED** |
| `rakuen_bt_edge1` | rb_rate (回/1000G) | +0.055 [+0.028, +0.085] | +0.045 [+0.014, +0.074] | -0.010 | [-0.054, +0.030] | ±0.042 | **UNDERPOWERED** |
| `rakuen_bt_edge1` | bonus_rate (回/1000G) | +0.184 [+0.127, +0.241] | +0.154 [+0.097, +0.201] | -0.031 | [-0.110, +0.044] | ±0.077 | **ALIVE** |
| `rakuen_jug_edge1` | payout (pp) | +0.719 [+0.422, +0.997] | +0.744 [+0.424, +1.170] | +0.025 | [-0.381, +0.565] | ±0.473 | **UNDERPOWERED** |
| `rakuen_jug_edge1` | rb_rate (回/1000G) | +0.073 [+0.042, +0.096] | +0.038 [+0.006, +0.083] | -0.035 | [-0.070, +0.024] | ±0.047 | **UNDERPOWERED** |
| `rakuen_jug_edge1` | bonus_rate (回/1000G) | +0.146 [+0.097, +0.189] | +0.126 [+0.075, +0.195] | -0.020 | [-0.082, +0.068] | ±0.075 | **UNDERPOWERED** |
| `rakuen_hana_edge1` | payout (pp) | +1.124 [+0.393, +1.710] | +1.359 [+0.303, +2.529] | +0.236 | [-0.926, +1.641] | ±1.284 | **UNDERPOWERED** |
| `rakuen_hana_edge1` | rb_rate (回/1000G) | +0.117 [+0.049, +0.175] | +0.137 [+0.058, +0.230] | +0.020 | [-0.075, +0.137] | ±0.106 | **UNDERPOWERED** |
| `rakuen_hana_edge1` | bonus_rate (回/1000G) | +0.251 [+0.149, +0.334] | +0.276 [+0.135, +0.428] | +0.025 | [-0.134, +0.212] | ±0.173 | **UNDERPOWERED** |
| `rakuen_clean_edge1_jug` | payout (pp) | +1.382 [+0.983, +1.737] | +0.619 [+0.113, +1.216] | -0.763 | [-1.354, -0.028] | ±0.663 | **WEAKENED** |
| `rakuen_clean_edge1_jug` | rb_rate (回/1000G) | +0.107 [+0.068, +0.138] | +0.030 [-0.012, +0.082] | -0.078 | [-0.127, -0.009] | ±0.059 | **DEAD** |
| `rakuen_clean_edge1_jug` | bonus_rate (回/1000G) | +0.245 [+0.185, +0.296] | +0.112 [+0.037, +0.206] | -0.133 | [-0.217, -0.018] | ±0.100 | **WEAKENED** |
| `rakuen_clean_edge1_bt` | payout (pp) | +1.534 [+1.059, +2.045] | +0.700 [-0.143, +1.438] | -0.834 | [-1.810, +0.036] | ±0.923 | **UNDERPOWERED** |
| `rakuen_clean_edge1_bt` | rb_rate (回/1000G) | +0.070 [+0.038, +0.106] | +0.037 [+0.006, +0.068] | -0.033 | [-0.081, +0.011] | ±0.046 | **UNDERPOWERED** |
| `rakuen_clean_edge1_bt` | bonus_rate (回/1000G) | +0.222 [+0.159, +0.292] | +0.121 [+0.040, +0.194] | -0.101 | [-0.206, -0.004] | ±0.101 | **WEAKENED** |
| `rakuen_dd_jug` | payout (pp) | +2.307 [+1.775, +2.784] | +2.101 [+1.263, +2.873] | -0.206 | [-1.155, +0.732] | ±0.943 | **ALIVE** |
| `rakuen_dd_jug` | rb_rate (回/1000G) | +0.271 [+0.208, +0.331] | +0.308 [+0.227, +0.385] | +0.037 | [-0.064, +0.135] | ±0.100 | **ALIVE** |
| `rakuen_dd_jug` | bonus_rate (回/1000G) | +0.424 [+0.326, +0.512] | +0.434 [+0.296, +0.558] | +0.010 | [-0.151, +0.169] | ±0.160 | **ALIVE** |
| `rakuen_dd_hana` | payout (pp) | +6.227 [+4.906, +7.530] | +6.901 [+5.767, +8.334] | +0.674 | [-1.011, +2.678] | ±1.845 | **ALIVE** |
| `rakuen_dd_hana` | rb_rate (回/1000G) | +0.461 [+0.372, +0.553] | +0.442 [+0.353, +0.550] | -0.019 | [-0.147, +0.122] | ±0.135 | **ALIVE** |
| `rakuen_dd_hana` | bonus_rate (回/1000G) | +0.966 [+0.782, +1.148] | +1.020 [+0.853, +1.213] | +0.054 | [-0.185, +0.327] | ±0.256 | **ALIVE** |
| `rakuen_dd_bt` | payout (pp) | +2.283 [+1.558, +2.971] | +2.956 [+2.135, +3.976] | +0.674 | [-0.376, +1.899] | ±1.137 | **ALIVE** |
| `rakuen_dd_bt` | rb_rate (回/1000G) | +0.089 [+0.048, +0.131] | +0.112 [+0.055, +0.171] | +0.022 | [-0.047, +0.095] | ±0.071 | **UNDERPOWERED** |
| `rakuen_dd_bt` | bonus_rate (回/1000G) | +0.262 [+0.169, +0.352] | +0.358 [+0.256, +0.480] | +0.096 | [-0.039, +0.251] | ±0.145 | **UNDERPOWERED** |
| `rakuen_dd_at` | payout (pp) | +2.129 [+1.450, +2.744] | +1.625 [+0.884, +2.394] | -0.504 | [-1.464, +0.542] | ±1.003 | **ALIVE** |
| `k1_jug_edge1` | payout (pp) | +0.114 [-0.110, +0.346] | +0.014 [-0.341, +0.390] | -0.100 | [-0.533, +0.338] | ±0.435 | **NO_BASELINE** |
| `k1_jug_edge1` | rb_rate (回/1000G) | -0.014 [-0.041, +0.012] | +0.052 [+0.014, +0.087] | +0.066 | [+0.020, +0.112] | ±0.046 | **NO_BASELINE** |
| `k1_jug_edge1` | bonus_rate (回/1000G) | +0.032 [-0.011, +0.078] | +0.075 [+0.012, +0.139] | +0.042 | [-0.035, +0.120] | ±0.077 | **NO_BASELINE** |
| `mitoya_jug_edge1` | payout (pp) | +1.958 [+1.711, +2.187] | +1.536 [+1.044, +1.985] | -0.421 | [-0.963, +0.106] | ±0.534 | **ALIVE** |
| `mitoya_jug_edge1` | rb_rate (回/1000G) | +0.204 [+0.175, +0.225] | +0.153 [+0.098, +0.204] | -0.051 | [-0.108, +0.010] | ±0.059 | **ALIVE** |
| `mitoya_jug_edge1` | bonus_rate (回/1000G) | +0.356 [+0.317, +0.388] | +0.280 [+0.198, +0.356] | -0.076 | [-0.163, +0.011] | ±0.087 | **ALIVE** |

## 監視対象の由来

- `mitoya_jug_corner1` — document/mitoya_theory.md §2.1 h_jug corner1　※陽性対照。2026-04-27 に消失済みと判定されている（追試6・追試7）。この仕組みが DEAD を出せなければ検知器として使えない
- `k7_jug_kakuban1` — document/kamata7_theory.md §2.1a　※陰性対照。追試8・追試9で設定差なしと判定済み。NO_BASELINE が出るのが正しい
- `k7_at_kakuban1` — backtest/results/regime/FINDINGS.md 追試2（AT一般 -1.205pp）　※AT機は bb_count/rb_count が意味を持たないため payout のみ。追試8の回転数分解は未実施の主張
- `rakuen_bt_edge1` — document/rakuen_theory.md §2.1b（技術介入 +1.127pp）　※2026-07-06 に島配列の工事あり。machine_layout_history の日付次元で工事前後それぞれ正しい位置が当たるので、期間の打ち切りは不要になった（旧: date_max=20260705）
- `rakuen_jug_edge1` — document/rakuen_theory.md §2.1b（ジャグ +0.349pp）　※旧§2.1bの端番定義。§2.1cで rakuen_clean_edge1_jug に置き換わったが旧定義の生死も追う。date_max=20260705 は machine_layout_history 導入前の暫定措置なので撤去（load_frame が日付結合するようになった）
- `rakuen_hana_edge1` — document/rakuen_theory.md §2.1b（ハナハナ +0.869pp）　※旧§2.1bの端番定義。date_max=20260705 は machine_layout_history 導入前の暫定措置なので撤去
- `rakuen_clean_edge1_jug` — document/rakuen_theory.md §2.1c / registry rk-clean-edge1-jug（ジャグ +1.207pp [+0.784,+1.638]、6期中6期有意）　※現行の端番定義。frame/interior_split/special を除いた clean 列の depth=1。工事前後の両エポックで成立とされているため期間は打ち切らない
- `rakuen_clean_edge1_bt` — document/rakuen_theory.md §2.1c / registry rk-clean-edge1-bt（技術介入 +1.403pp [+0.914,+1.826]、6期中5期有意）　※§2.1c は jug/hana を先に取る排他カテゴリで測っているので universe も同じ優先順で切る
- `rakuen_dd_jug` — document/rakuen_theory.md §3.1a / registry rk-event-dd-jug（イベントDD {22,5,11,25,15}）　※日付軸。同日対比が作れないので cross_day（機種構成調整済みの日次水準を、対象日 vs 対照日で比較）
- `rakuen_dd_hana` — document/rakuen_theory.md §3.1a / registry rk-event-dd-hana（イベントDD {7,17,27}）　※全カテゴリ中で最も日差が大きい。位置軸は検定不能（外周配置）なので、このホールのハナハナはこの claim が唯一の監視対象
- `rakuen_dd_bt` — document/rakuen_theory.md §3.1a / registry rk-event-dd-bt（イベントDD {30,22,11}）
- `rakuen_dd_at` — document/rakuen_theory.md §3.1a / registry rk-event-dd-at（イベントDD {30,22,11,10}）　※AT機は bb_count/rb_count が概念的に対応しないため payout のみ
- `k1_jug_edge1` — backtest/results/regime/FINDINGS.md 追試3（蒲田1 +0.068pp、プールでは検出されず）　※蒲田1は rank_from_aisle が全NULLのためセクション端で代用。追試3ではプール平均で null
- `mitoya_jug_edge1` — backtest/results/regime/FINDINGS.md 追試3（みとや +1.575pp）　※通路角番とは別軸。角番1の死亡がセクション端にも及んでいるかを見る
