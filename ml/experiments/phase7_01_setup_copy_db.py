"""
Phase 7: Rank Prediction - Step 1: Setup Copy DB with Target Columns

Creates a copy of マルハンメガシティ2000-蒲田7.db and adds target columns:
- is_rank_1: machine_type_rank_diff == 1
- is_top_3: machine_type_rank_diff <= 3
- is_top_5: machine_type_rank_diff <= 5
"""

import sqlite3
import shutil
from pathlib import Path

# Paths - handle worktree vs main project
import os
# In worktree: /2026project/.claude/worktrees/reverent-ishizaka-4201c5
# Need: /2026project
worktree_root = Path(__file__).parent.parent.parent
potential_project_root = worktree_root.parent.parent.parent.parent
if (potential_project_root / "db").exists():
    PROJECT_ROOT = potential_project_root
else:
    # Fallback to hardcoded path
    PROJECT_ROOT = Path("C:\\Users\\apto117\\Documents\\pachinko-analyzer\\src\\2026project")

ORIGINAL_DB = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
EXPERIMENTS_DIR = PROJECT_ROOT / "db" / "experiments"
COPY_DB = EXPERIMENTS_DIR / "マルハンメガシティ2000-蒲田7_rank_exp.db"

def setup_copy_db():
    """Create copy DB and add target columns."""

    # 1. Create experiments directory
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[OK] Created {EXPERIMENTS_DIR}")

    # 2. Copy DB
    if COPY_DB.exists():
        COPY_DB.unlink()
        print(f"  Removed existing copy")

    shutil.copy2(ORIGINAL_DB, COPY_DB)
    print(f"[OK] Copied DB to {COPY_DB.name}")
    print(f"  Size: {COPY_DB.stat().st_size / 1024 / 1024:.1f} MB")

    # 3. Add target columns
    conn = sqlite3.connect(COPY_DB)
    cur = conn.cursor()

    try:
        # Check if columns already exist
        cur.execute("PRAGMA table_info(daily_machine_type_summary)")
        cols = {c[1] for c in cur.fetchall()}

        # Add missing target columns
        if "is_rank_1" not in cols:
            cur.execute("ALTER TABLE daily_machine_type_summary ADD COLUMN is_rank_1 INTEGER DEFAULT 0")
            print("[OK] Added is_rank_1 column")

        if "is_top_3" not in cols:
            cur.execute("ALTER TABLE daily_machine_type_summary ADD COLUMN is_top_3 INTEGER DEFAULT 0")
            print("[OK] Added is_top_3 column")

        if "is_top_5" not in cols:
            cur.execute("ALTER TABLE daily_machine_type_summary ADD COLUMN is_top_5 INTEGER DEFAULT 0")
            print("[OK] Added is_top_5 column")

        # Populate target columns from machine_type_rank_diff
        cur.execute("""
            UPDATE daily_machine_type_summary
            SET is_rank_1 = CASE WHEN machine_type_rank_diff = 1 THEN 1 ELSE 0 END
        """)
        rank1_count = cur.rowcount

        cur.execute("""
            UPDATE daily_machine_type_summary
            SET is_top_3 = CASE WHEN machine_type_rank_diff <= 3 THEN 1 ELSE 0 END
        """)
        top3_count = cur.rowcount

        cur.execute("""
            UPDATE daily_machine_type_summary
            SET is_top_5 = CASE WHEN machine_type_rank_diff <= 5 THEN 1 ELSE 0 END
        """)
        top5_count = cur.rowcount

        conn.commit()
        print(f"[OK] Populated target columns ({rank1_count} rows updated)")

        # Verify target distribution
        cur.execute("SELECT COUNT(*) FROM daily_machine_type_summary")
        total = cur.fetchone()[0]

        cur.execute("SELECT SUM(is_rank_1) FROM daily_machine_type_summary")
        rank1_sum = cur.fetchone()[0] or 0

        cur.execute("SELECT SUM(is_top_3) FROM daily_machine_type_summary")
        top3_sum = cur.fetchone()[0] or 0

        cur.execute("SELECT SUM(is_top_5) FROM daily_machine_type_summary")
        top5_sum = cur.fetchone()[0] or 0

        print(f"\n=== Target Distribution ===")
        print(f"Total rows: {total}")
        print(f"is_rank_1: {rank1_sum:5d} ({100*rank1_sum/total:5.2f}%)")
        print(f"is_top_3:  {top3_sum:5d} ({100*top3_sum/total:5.2f}%)")
        print(f"is_top_5:  {top5_sum:5d} ({100*top5_sum/total:5.2f}%)")

    finally:
        conn.close()

    print(f"\n[OK] Copy DB setup complete!")
    return COPY_DB

if __name__ == "__main__":
    copy_db_path = setup_copy_db()
    print(f"\nReady for Phase 2: {copy_db_path}")
