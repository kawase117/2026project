# 2026-09-28(月) 答え合わせ

対象: forward凍結ルール17本、登録済みannounce3件(蒲田1・楽園×2)。ARROW池上は9/28分DB未取り込みのため未採点。

## 1. forward凍結ルールの結果

| ルール | ホール | mean_edge | mean_diff | 判定 |
|---|---|---:|---:|---|
| **rakuen_block2247_position_follow** | 楽園蒲田 | **+2,925.3** | +3,107.2 | ◎ 大勝ち |
| zassiki_model_term60_top3 | 雑色 | +784.0 | +655.2 | ◎ |
| heiwajima_model_term60_top3 | 平和島 | +655.9 | +555.9 | ○ |
| k7_at_histdiff_ex2026_top3 | 蒲田7 | +505.0 | +400.0 | ○ |
| k7_jug_hit104_top3 | 蒲田7 | +346.1 | +433.3 | ○ |
| zassiki_jug_fixed_top3 | 雑色 | +275.7 | +199.7 | ○ |
| kamata1_model_term60_top3 | 蒲田1 | +212.8 | +78.6 | ○ |
| k7_at_histdiff_top3 | 蒲田7 | +171.7 | +66.7 | ○ |
| mitoya_model_gratio_top2 | みとや | +152.3 | +269.5 | ○ |
| rakuen_model_term60_top3 | 楽園蒲田 | +117.1 | +299.1 | ○ |
| mitoya_model_term60_top3 | みとや | +18.7 | +136.0 | △ |
| k7_monday_model_gratio_top2 | 蒲田7 | +29.2 | -17.2 | △ |
| k7_jug_kakuban1_avoid_rb_top3 / k7_jug_rb_top3 | 蒲田7 | -120.5 | -33.3 | △ 同一ピック |
| kamata7_model_term60_top3 | 蒲田7 | -85.0 | -131.4 | △ |
| k1_jug_plain_rbz_top3 | 蒲田1 | -327.7 | -366.7 | ✗ |
| rakuen_jug_renovation_rb_top3 | 楽園蒲田 | -574.4 | -460.0 | ✗ |

**総括**: 17本中プラスが12本、明確なマイナスは2本(k1_jug_plain_rbz、rakuen_jug_renovation_rb)。rakuen_block2247は前日9/27(+2,955.6)に続き2日連続の大勝ちで、バンドリ！2247-2250バンクの再現性が高い。ジャグ台粒度ルール(k7_jug_rb/kakuban1_avoid)は前日横ばい・今日もマイナスで、既存instinct「蒲田7ジャグ日次台粒度選択は負」を追認し続けている。

## 2. 登録済みannounceの採点

### 蒲田1(999999Q9Q、語呂合わせ予想)6claims

| 機種 | rank | 判定 |
|---|---:|---|
| 東京喰種 | 47/48 | miss |
| ミリオンゴッド‐神々の軌跡‐ | 45/48 | miss |
| ゴッドイーター リザレクション | 33/48 | miss |
| 甲鉄城のカバネリ 海門(うなと)決戦 | 28/48 | miss |
| リコリス・リコイル | 44/48 | miss |
| バジリスク～甲賀忍法帖～絆2 天膳 BLACK EDITION | — | 判定不能(蒲田1に設置3台以上なし) |

**6件中0hit**。語呂合わせによる機種解読は全滅。[[project-kawasakislot-selfreport-inflated]]系の「予想アカウントの当たり」への懐疑は999999Q9Qにも当てはまる可能性がある。

### 楽園蒲田(kawasakislot)2claims

| 機種 | rank | 判定 |
|---|---:|---|
| 東京喰種 | 21/57 | miss |
| 甲鉄城のカバネリ 海門(うなと)決戦 | 8/57(score+873) | miss(閾値未達だが決して弱くはない) |

### 楽園蒲田(minnade777judge)3claims

| claim | 判定 |
|---|---|
| 東京喰種(named) | miss(同上) |
| 甲鉄城のカバネリ(named) | miss(同上) |
| 全台上位2つ機種複数(zentaikei_count≥2) | **hit** |

zentaikei_count的中の内訳: **バジリスク～甲賀忍法帖～絆2 天膳 BLACK EDITION**(4台、平均+3,072、age635=established)と**バンドリ！**(4台、平均+3,107.2、age635)。バンドリ！の数値はforwardルール`rakuen_block2247_position_follow`の今日のmean_diff(+3,107.2)と完全一致しており、同じバンクが両方の判定を牽引した。

興味深い点として、蒲田1の999999Q9Qが語呂で挙げていた「バジリスク～甲賀忍法帖～絆2 天膳 BLACK EDITION」は蒲田1では設置台数不足で判定不能だったが、**同じ機種名が楽園蒲田側では実際に全台系の一角として的中している**。ホールをまたいだ偶然の一致であり、蒲田1の語呂解釈自体の妥当性を裏付けるものではない([[feedback-no-cross-hall-pooling]]の原則通り、機種名が同じでもホールが違えば無関係)。

## 3. 今後のアクション

- バンドリ！2247-2250バンクは2日連続の大勝ちで、`rakuen_block2247_position_follow`ルールのsuccess_criterion(在庫のエントリー日数・CI基準)への到達が近づいている。次回の答え合わせで累積成績を確認する。
- 999999Q9Qの語呂合わせ予想は6件中0hitで、今回に限れば的中実績への懐疑を強める材料になった。継続して的中率を追跡する。
- k1_jug_plain_rbz_top3とrakuen_jug_renovation_rb_top3はマイナスが続く場合、success_criterion未達での棄却を検討する。
