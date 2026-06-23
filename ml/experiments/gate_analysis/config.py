from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = PROJECT_ROOT / "ml" / "experiments" / "gate_analysis" / "results"
COORDS_2F_PATH = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
COORDS_3F_PATH = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_DB_FALLBACK = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"

EVENT_DDS = frozenset({1, 7, 11, 17, 21, 22, 27, 31})
ANNIVERSARY_MMDD = "0707"
GAMES_MIN = 400
A_THRESHOLD = 104.0
N_THRESHOLD = 106.0
GATE_WINDOW_DAYS = 90
GATE_QUANTILES = (0.60, 0.70, 0.80)
PRIMARY_GATE_QUANTILE = 0.70

SEGMENT_ORDER = (
    "2F_L_N",
    "2F_R_N",
    "3F_L_A",
    "3F_L_N",
    "3F_R_A",
    "3F_R_N",
)
