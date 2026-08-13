"""Shared configuration for the X monitoring pipeline."""

from pathlib import Path


ACCOUNTS = {
    "kawasakislot": {"hall": "rakuen_kamata", "role": "予告+答え合わせ"},
    "slokotae7": {"hall": "rakuen_kamata", "role": "答え合わせ"},
    "fanta_tenchou": {"hall": "rakuen_kamata", "role": "店長"},
    "999999Q9Q": {"hall": "kamata7_kamata1", "role": "予告+答え合わせ"},
    "j75gJ3j1539G": {"hall": "kamata7_kamata1", "role": "蒲田一店長"},
    "ngc2070r136a1": {"hall": "kamata7_kamata1", "role": "蒲田七店長"},
    "kengyo_niki": {"hall": "hiroki", "role": "答え合わせ"},
    "sloneko222": {"hall": "arrow_ikegami_mitoya_omori", "role": "結果報告"},
}

BASE_DIR = Path(__file__).resolve().parent
AUTH_STATE_PATH = BASE_DIR / ".auth" / "state.json"
DB_PATH = BASE_DIR / "state.db"
IMAGES_DIR = BASE_DIR / "images"
