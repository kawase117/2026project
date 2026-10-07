from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "ml" / "experiments" / "results" / "jug_rb_setting_prediction"
DEFAULT_HALL = "蒲田7"

HALL_DBS: "OrderedDict[str, Path]" = OrderedDict(
    {
        "蒲田7": PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db",
        "蒲田1": PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db",
        "ARROW": PROJECT_ROOT / "db" / "ARROW池上店.db",
        "レイトギャップ": PROJECT_ROOT / "db" / "レイトギャップ平和島.db",
        "みとや": PROJECT_ROOT / "db" / "みとや大森町店.db",
        "楽園蒲田": PROJECT_ROOT / "db" / "楽園蒲田店.db",
        "ヒロキ": PROJECT_ROOT / "db" / "ヒロキ東口店.db",
        "ザシティ": PROJECT_ROOT / "db" / "ザ-シティ-ベルシティ雑色店.db",
        "金時": PROJECT_ROOT / "db" / "金時京急蒲田店.db",
    }
)

HALL_SLUGS: dict[str, str] = {
    "蒲田7": "kamata7",
    "蒲田1": "kamata1",
    "ARROW": "arrow",
    "レイトギャップ": "lategap",
    "みとや": "mitoya",
    "楽園蒲田": "rakuen",
    "ヒロキ": "hiroki",
    "ザシティ": "zashiti",
    "金時": "kintoki",
}

JUGGLER_UNKNOWN_FAMILY_KEY = "UNKNOWN"
JUGGLER_FALLBACK_FAMILY_KEY = "IMEX"

JUGGLER_FAMILY_SPECS = {
    # 数値は jugglersnet.com / 1geki.jp 等の公表解析値と照合済み（2026-07-06）
    "IMEX": {
        "family_name": "アイムジャグラーEX系",
        "machine_keyword": "アイムジャグラー",
        # 2026-07-06 ユーザー提供の実機解析値で修正
        "settings": {
            1: {"rb_probability": 1 / 439.8, "bb_probability": 1 / 273.1, "payout_rate": 97.0},
            2: {"rb_probability": 1 / 399.6, "bb_probability": 1 / 269.7, "payout_rate": 98.0},
            3: {"rb_probability": 1 / 331.0, "bb_probability": 1 / 269.7, "payout_rate": 99.5},
            4: {"rb_probability": 1 / 315.1, "bb_probability": 1 / 259.0, "payout_rate": 101.1},
            5: {"rb_probability": 1 / 255.0, "bb_probability": 1 / 259.0, "payout_rate": 103.3},
            6: {"rb_probability": 1 / 255.0, "bb_probability": 1 / 255.0, "payout_rate": 105.5},
        },
    },
    "MYV": {
        "family_name": "マイジャグラーV",
        "machine_keyword": "マイジャグラーV",
        "settings": {
            1: {"rb_probability": 1 / 409.6, "bb_probability": 1 / 273.1, "payout_rate": 97.0},
            2: {"rb_probability": 1 / 385.5, "bb_probability": 1 / 270.8, "payout_rate": 98.0},
            3: {"rb_probability": 1 / 336.1, "bb_probability": 1 / 266.4, "payout_rate": 99.9},
            4: {"rb_probability": 1 / 290.0, "bb_probability": 1 / 254.0, "payout_rate": 102.8},
            5: {"rb_probability": 1 / 268.6, "bb_probability": 1 / 240.1, "payout_rate": 105.3},
            6: {"rb_probability": 1 / 229.1, "bb_probability": 1 / 229.1, "payout_rate": 109.4},
        },
    },
    "GOGO3": {
        "family_name": "ゴーゴージャグラー3",
        "machine_keyword": "ゴーゴージャグラー3",
        "settings": {
            1: {"rb_probability": 1 / 378.8, "bb_probability": 1 / 259.0, "payout_rate": 96.5},
            2: {"rb_probability": 1 / 370.3, "bb_probability": 1 / 258.0, "payout_rate": 97.8},
            3: {"rb_probability": 1 / 337.8, "bb_probability": 1 / 257.0, "payout_rate": 99.8},
            4: {"rb_probability": 1 / 311.4, "bb_probability": 1 / 254.0, "payout_rate": 101.9},
            5: {"rb_probability": 1 / 288.7, "bb_probability": 1 / 247.3, "payout_rate": 104.0},
            6: {"rb_probability": 1 / 262.1, "bb_probability": 1 / 234.9, "payout_rate": 106.5},
        },
    },
    "FUNKY2": {
        "family_name": "ファンキージャグラー2",
        "machine_keyword": "ファンキージャグラー2",
        "settings": {
            1: {"rb_probability": 1 / 407.1, "bb_probability": 1 / 266.4, "payout_rate": 97.4},
            2: {"rb_probability": 1 / 402.1, "bb_probability": 1 / 259.0, "payout_rate": 98.4},
            3: {"rb_probability": 1 / 376.6, "bb_probability": 1 / 256.0, "payout_rate": 99.5},
            4: {"rb_probability": 1 / 329.5, "bb_probability": 1 / 249.2, "payout_rate": 101.8},
            5: {"rb_probability": 1 / 308.4, "bb_probability": 1 / 240.1, "payout_rate": 104.0},
            6: {"rb_probability": 1 / 262.1, "bb_probability": 1 / 219.9, "payout_rate": 106.5},
        },
    },
    "HAPPY8": {
        "family_name": "ハッピージャグラーVIII",
        "machine_keyword": "ハッピージャグラーVIII",
        "settings": {
            1: {"rb_probability": 1 / 409.6, "bb_probability": 1 / 287.4, "payout_rate": 96.0},
            2: {"rb_probability": 1 / 390.1, "bb_probability": 1 / 282.5, "payout_rate": 97.2},
            3: {"rb_probability": 1 / 334.4, "bb_probability": 1 / 277.7, "payout_rate": 98.9},
            4: {"rb_probability": 1 / 300.6, "bb_probability": 1 / 270.8, "payout_rate": 101.1},
            5: {"rb_probability": 1 / 270.8, "bb_probability": 1 / 262.1, "payout_rate": 103.9},
            6: {"rb_probability": 1 / 242.7, "bb_probability": 1 / 242.7, "payout_rate": 106.7},
        },
    },
    "UMJ": {
        "family_name": "ウルトラミラクルジャグラー",
        "machine_keyword": "ウルトラミラクルジャグラー",
        "settings": {
            1: {"rb_probability": 1 / 425.6, "bb_probability": 1 / 267.5, "payout_rate": 97.0},
            2: {"rb_probability": 1 / 402.1, "bb_probability": 1 / 261.1, "payout_rate": 98.1},
            3: {"rb_probability": 1 / 350.5, "bb_probability": 1 / 256.0, "payout_rate": 99.8},
            4: {"rb_probability": 1 / 322.8, "bb_probability": 1 / 242.7, "payout_rate": 102.1},
            5: {"rb_probability": 1 / 297.9, "bb_probability": 1 / 233.2, "payout_rate": 104.5},
            6: {"rb_probability": 1 / 277.7, "bb_probability": 1 / 216.3, "payout_rate": 108.1},
        },
    },
    "GALS": {
        "family_name": "ジャグラーガールズSS",
        "machine_keyword": "ジャグラーガールズ",
        "settings": {
            1: {"rb_probability": 1 / 381.0, "bb_probability": 1 / 273.1, "payout_rate": 97.0},
            2: {"rb_probability": 1 / 350.5, "bb_probability": 1 / 270.8, "payout_rate": 97.9},
            3: {"rb_probability": 1 / 316.6, "bb_probability": 1 / 260.1, "payout_rate": 99.9},
            4: {"rb_probability": 1 / 281.3, "bb_probability": 1 / 250.1, "payout_rate": 102.1},
            5: {"rb_probability": 1 / 270.8, "bb_probability": 1 / 243.6, "payout_rate": 104.0},
            6: {"rb_probability": 1 / 252.1, "bb_probability": 1 / 226.0, "payout_rate": 107.5},
        },
    },
    "MISTER": {
        "family_name": "ミスタージャグラー",
        "machine_keyword": "ミスタージャグラー",
        "settings": {
            1: {"rb_probability": 1 / 374.5, "bb_probability": 1 / 268.6, "payout_rate": 97.0},
            2: {"rb_probability": 1 / 354.2, "bb_probability": 1 / 267.5, "payout_rate": 98.0},
            3: {"rb_probability": 1 / 331.0, "bb_probability": 1 / 260.1, "payout_rate": 99.8},
            4: {"rb_probability": 1 / 291.3, "bb_probability": 1 / 249.2, "payout_rate": 102.7},
            5: {"rb_probability": 1 / 257.0, "bb_probability": 1 / 240.9, "payout_rate": 105.5},
            6: {"rb_probability": 1 / 237.4, "bb_probability": 1 / 237.4, "payout_rate": 107.3},
        },
    },
    # ジャグラー系ではないが、BB/RBが設定で変わる非AT・ボーナストリガー機として同じ
    # 尤度推定に載せる（site777_setting_estimator.py はこの辞書を machine_keyword で
    # 汎用的に走査するため、JUGGLER_FAMILY_ORDER/MATCHERS には追加しない＝蒲田7/蒲田1
    # 向けジャグラー専用パイプラインには影響しない）。
    # 出典: document/machine_master_research/machine_master.csv
    # （1geki.jp解析値）。設定3・4は元データ未掲載のため欠落させたまま扱う
    # （estimate_setting は settings dict のキーだけを見るので部分欠損でも動く）。
    # 2026-09-21 ユーザー指示で、BB/RBを一撃の新ハナビのページ（/slot/s_shinhanabi/、
    # 設定判別 /0/ も同値）の現在値に合わせた。以前は取得時点の旧値（設定2・5・6のRBと設定6のBB）。
    # 出玉率(payout_rate)は旧値のまま（ページは完全攻略時の102.0/104.0/106.5/109.0%を載せる）。
    "HANABI_SHIN": {
        "family_name": "新ハナビ",
        "machine_keyword": "新ハナビ",
        "source": "一撃(2026-09-21)",
        "settings": {
            1: {"rb_probability": 1 / 356.2, "bb_probability": 1 / 277.7, "payout_rate": 97.7},
            2: {"rb_probability": 1 / 331.0, "bb_probability": 1 / 268.6, "payout_rate": 99.3},
            5: {"rb_probability": 1 / 306.2, "bb_probability": 1 / 256.0, "payout_rate": 104.4},
            6: {"rb_probability": 1 / 280.1, "bb_probability": 1 / 248.2, "payout_rate": 109.0},
        },
    },
    # 型式名「LB／スマスロサンダーVHA」の通り、site777の「LBサンダーV」と
    # machine_master の「スマスロ サンダーV」は同一機種（ユーザー提供の公式スペック表、
    # 2026-08-25）。設定3・4は未公表のため欠落させたまま扱う。
    "SANDER_V": {
        "family_name": "サンダーV",
        "machine_keyword": "サンダーV",
        "settings": {
            1: {"rb_probability": 1 / 434.0, "bb_probability": 1 / 277.7, "payout_rate": 98.5},
            2: {"rb_probability": 1 / 394.8, "bb_probability": 1 / 275.4, "payout_rate": 100.0},
            5: {"rb_probability": 1 / 344.9, "bb_probability": 1 / 270.8, "payout_rate": 102.9},
            6: {"rb_probability": 1 / 313.6, "bb_probability": 1 / 264.3, "payout_rate": 106.0},
        },
    },
    # 出典: 一撃 設定判別ページ https://1geki.jp/slot/s_versus_rexse/0/（2025-04-16更新）。
    # 2026-10-07 にユーザーがこの表(BIG/REG/合算・出玉率)を正と確認した。設定1,2,5,6の4設定機で、設定3・4は存在しない（補間しないこと）。
    # 機械割は出玉率(市場予測)。旧値（スペックページ由来のBB 1/264.3,260.1,244.5,237.4・RB 1/344.9,334.4,292.6,277.7）は誤りだった。
    "VERSUS_REVISE": {
        "family_name": "バーサスリヴァイズ",
        "machine_keyword": "バーサスリヴァイズ",
        "settings": {
            1: {"rb_probability": 1 / 374.5, "bb_probability": 1 / 292.6, "payout_rate": 99.3},
            2: {"rb_probability": 1 / 341.3, "bb_probability": 1 / 284.9, "payout_rate": 101.1},
            5: {"rb_probability": 1 / 319.7, "bb_probability": 1 / 275.4, "payout_rate": 103.5},
            6: {"rb_probability": 1 / 292.6, "bb_probability": 1 / 264.3, "payout_rate": 105.8},
        },
    },
    # ユーザー提供の公式スペック表（2026-08-25）。設定1,2,5,6の4段階機。
    "ALEX_BRIGHT": {
        "family_name": "アレックス ブライト",
        "machine_keyword": "アレックス ブライト",
        "settings": {
            1: {"rb_probability": 1 / 428.3, "bb_probability": 1 / 309.1, "payout_rate": 98.8},
            2: {"rb_probability": 1 / 409.6, "bb_probability": 1 / 303.4, "payout_rate": 100.6},
            5: {"rb_probability": 1 / 366.1, "bb_probability": 1 / 295.2, "payout_rate": 103.5},
            6: {"rb_probability": 1 / 312.1, "bb_probability": 1 / 287.4, "payout_rate": 106.8},
        },
    },
    # 型式名「LBケロット5ND05H」の通り、site777の「LBケロット5」と同一機種
    # （ユーザー提供の公式スペック表、2026-08-25）。ケロット4とは別機種のため流用不可、
    # 混同しないこと。設定1〜6フルスペックの機種。
    "KEROTTO5": {
        "family_name": "ケロット5",
        "machine_keyword": "ケロット5",
        "settings": {
            1: {"rb_probability": 1 / 350.5, "bb_probability": 1 / 232.4, "payout_rate": 98.2},
            2: {"rb_probability": 1 / 341.3, "bb_probability": 1 / 230.8, "payout_rate": 99.1},
            3: {"rb_probability": 1 / 324.4, "bb_probability": 1 / 229.1, "payout_rate": 101.1},
            4: {"rb_probability": 1 / 299.3, "bb_probability": 1 / 218.5, "payout_rate": 104.5},
            5: {"rb_probability": 1 / 274.2, "bb_probability": 1 / 215.5, "payout_rate": 107.0},
            6: {"rb_probability": 1 / 239.2, "bb_probability": 1 / 204.8, "payout_rate": 111.0},
        },
    },
    # ユーザー提供の公式スペック表（2026-08-25）。設定1,2,5,6の4段階機。
    # site777の表記は「スマスロ ハナビ」（新ハナビとは別機種）。
    "HANABI_SUMASLO": {
        "family_name": "スマスロ ハナビ",
        "machine_keyword": "スマスロ ハナビ",
        "source": "公式スペック表(ユーザー提供 2026-08-25、一撃 /slot/l_hanabi/ と一致)",
        "settings": {
            1: {"rb_probability": 1 / 394.8, "bb_probability": 1 / 297.9, "payout_rate": 98.6},
            2: {"rb_probability": 1 / 358.1, "bb_probability": 1 / 292.6, "payout_rate": 100.4},
            5: {"rb_probability": 1 / 313.6, "bb_probability": 1 / 284.9, "payout_rate": 103.0},
            6: {"rb_probability": 1 / 282.5, "bb_probability": 1 / 273.1, "payout_rate": 106.4},
        },
    },
    # ユーザー提供のスペック表（2026-09-30、一撃 /slot/lb_fj2/ と一致）。設定3は未掲載の5段階機。
    # スペックのBIGは SUPER BIG+BIG の合算で、SUPER BIG 後のBT「不二子TIME」は約1/16で
    # ボーナスに当選する。site777のBB欄がこれを数えている疑いがある（2026-09-30 楽園3142は
    # 2288GでBB33=1/69。設定6の期待13回を大きく超え、どの設定でも説明できない）。
    # そのため use_bb=False でBBを尤度から外し、RB(REG)だけで推定する。
    # 2026-09-30 に楽園の過去実績（ana-slo由来DB、2025-12-22〜2026-09-29、G1500以上391台日）で
    # 確認済み: BB 1/147（設定6の1/172を上回る）、設定6の期待の上側2.5%を超えた台日が18.2%
    # （正しく数えていれば約2.5%以下）、BB/RB件数比2.16（スペック1.23〜1.32）、台日のBBとRBの
    # 相関-0.03。RBは1/318で設定1(1/321)並み・下振れ1.3%/上振れ0.0%で正常。他のBT機
    # （ハーレムエース・クレア・ケロット5・サンダーV）はBB/RBともスペックどおりで異常なし。
    # 未確認: サイトセブンの当日BBがana-slo由来のBBと同じ定義か（9/30分がDBに入ったら同じ台で照合）。
    # payout_rate は下限値。
    "FUJIKO_BT": {
        "family_name": "不二子BT",
        "machine_keyword": "不二子BT",
        "source": "一撃 /slot/lb_fj2/ (ユーザー提供 2026-09-30)",
        "settings": {
            1: {"rb_probability": 1 / 321.3, "bb_probability": 1 / 252.1, "payout_rate": 97.6, "use_bb": False},
            2: {"rb_probability": 1 / 304.8, "bb_probability": 1 / 239.2, "payout_rate": 99.4, "use_bb": False},
            4: {"rb_probability": 1 / 278.9, "bb_probability": 1 / 219.2, "payout_rate": 102.9, "use_bb": False},
            5: {"rb_probability": 1 / 252.1, "bb_probability": 1 / 205.4, "payout_rate": 105.4, "use_bb": False},
            6: {"rb_probability": 1 / 227.6, "bb_probability": 1 / 172.5, "payout_rate": 107.4, "use_bb": False},
        },
    },
    # ユーザー提供のスペック表（2026-09-30、一撃 /slot/s_kurea3/ と一致）。設定1〜6フルスペックの
    # ボーナストリガー機。site777の表記は「LBクレアの秘宝伝ボーナストリガーver.」。
    # BIG当選で必ずBTが発動する。payout_rate は下限値。
    "CLAIRE_BT": {
        "family_name": "クレアの秘宝伝BT",
        "machine_keyword": "クレアの秘宝伝",
        "source": "一撃 /slot/s_kurea3/ (ユーザー提供 2026-09-30)",
        "settings": {
            1: {"rb_probability": 1 / 383.3, "bb_probability": 1 / 299.3, "payout_rate": 98.1},
            2: {"rb_probability": 1 / 376.6, "bb_probability": 1 / 293.9, "payout_rate": 99.2},
            3: {"rb_probability": 1 / 358.1, "bb_probability": 1 / 284.9, "payout_rate": 101.2},
            4: {"rb_probability": 1 / 334.4, "bb_probability": 1 / 274.2, "payout_rate": 103.7},
            5: {"rb_probability": 1 / 299.3, "bb_probability": 1 / 262.1, "payout_rate": 106.6},
            6: {"rb_probability": 1 / 247.3, "bb_probability": 1 / 240.1, "payout_rate": 112.3},
        },
    },
    # ユーザー提供のスペック表（2026-09-30）。設定1,2,5,6の4段階機。site777の表記は
    # 「翔べ！ハーレムエース」（BT機）。2026-09-30 楽園3210は5836GでBB27（1/216）と設定6の
    # 期待19回を上回るが、不二子BTほど極端ではなく3211は期待の範囲内なので、BBは尤度に入れる
    # （use_bb は付けない）。RB（REG）が主指標なのは他のBT機と同じ。payout_rate は下限値。
    "HAREM_ACE": {
        "family_name": "翔べ！ハーレムエース",
        "machine_keyword": "ハーレムエース",
        "source": "ユーザー提供スペック表 (2026-09-30)",
        "settings": {
            1: {"rb_probability": 1 / 560.1, "bb_probability": 1 / 402.1, "payout_rate": 98.1},
            2: {"rb_probability": 1 / 508.0, "bb_probability": 1 / 390.1, "payout_rate": 99.9},
            5: {"rb_probability": 1 / 409.6, "bb_probability": 1 / 343.1, "payout_rate": 104.7},
            6: {"rb_probability": 1 / 327.7, "bb_probability": 1 / 307.7, "payout_rate": 110.0},
        },
    },
}

JUGGLER_FAMILY_ORDER = ("IMEX", "MYV", "GOGO3", "FUNKY2", "HAPPY8")
JUGGLER_FAMILY_MATCHERS = (
    ("MYV", "マイジャグラーV"),
    ("GOGO3", "ゴーゴージャグラー3"),
    ("FUNKY2", "ファンキージャグラー2"),
    ("HAPPY8", "ハッピージャグラーVIII"),
    ("UMJ", "ウルトラミラクルジャグラー"),
    ("GALS", "ジャグラーガールズ"),
    ("MISTER", "ミスタージャグラー"),
    ("IMEX", "アイムジャグラー"),
)
