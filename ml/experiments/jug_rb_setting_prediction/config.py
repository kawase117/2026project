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
