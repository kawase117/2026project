"""Shared configuration for the X monitoring pipeline."""

from pathlib import Path


ACCOUNTS = {
    "kawasakislot": {"hall": "rakuen_kamata", "role": "予告+答え合わせ"},
    "slokotae7": {"hall": "rakuen_kamata", "role": "答え合わせ"},
    "fanta_tenchou": {"hall": "rakuen_kamata", "role": "店長"},
    "999999Q9Q": {"hall": "kamata7_kamata1", "role": "予告+答え合わせ"},
    # よこやん = 蒲田1の現店長。2026-09-01 就任（999999Q9Q が 2026-08-31 に
    # 「新店長は日野から殴り込み【よこやん店長】」「9月1日（火）メガシティ周年×
    # 新店長就任」と投稿）。予告本文がしばしば「投稿されている画像」を根拠に
    # するため、一次資料としてここを監視する。
    "yokoyan_777": {"hall": "kamata1", "role": "蒲田一店長"},
    # ⚠️ サトウは 2026-08-23 に蒲田1店長を退任し、8/26 からマルハン鷲宮店。
    # 蒲田1の一次資料としては使えない。過去分の参照用に残す。
    "j75gJ3j1539G": {"hall": "kamata7_kamata1", "role": "蒲田一店長(〜2026-08-23、以降は鷲宮店)"},
    "ngc2070r136a1": {"hall": "kamata7_kamata1", "role": "蒲田七店長"},
    # 楽園蒲田の予告を出すもう1つの媒体。2026-09-14・15 の予告はここが一次資料
    # だったが監視対象に入っておらず、backfill_search.py も対象外だった。
    "minnade777judge": {"hall": "rakuen_kamata", "role": "予告+答え合わせ"},
    "kengyo_niki": {"hall": "hiroki", "role": "答え合わせ"},
    "sloneko222": {"hall": "arrow_ikegami_mitoya_omori", "role": "結果報告"},
}

BASE_DIR = Path(__file__).resolve().parent
AUTH_STATE_PATH = BASE_DIR / ".auth" / "state.json"
DB_PATH = BASE_DIR / "state.db"
IMAGES_DIR = BASE_DIR / "images"
