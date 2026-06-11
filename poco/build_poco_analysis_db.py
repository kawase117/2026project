"""
poco_analysis.db 構築スクリプト

テーブル構成:
  poco_announcements  - 日次×ホール単位（曜日仕掛けの実績含む）
  poco_targets        - 日次×ホール×機種単位（発表機種の実績）

計算可能な曜日仕掛け:
  - 末尾N     : machine_detailed_results WHERE last_digit IN (N1, N2, ...)
  - 全台      : 全機種全台
  - 末尾ゾロ目  : is_zorome = 1
  - 並び末尾N  : 末尾Nの台番号から±window の範囲（3台並び=±2, 4台=±3, 5台=±4）
                EXISTS (SELECT 1 WHERE ABS(machine_number - anchor) <= window)

スキップ（位置情報が必要）:
  - 角、列、機種イチ、不明
  - 並びで末尾数字が取れないもの
"""

import sqlite3
import pandas as pd
import re
import sys
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR  = Path(__file__).parent.parent
POCO_CSV  = BASE_DIR / 'docs/poco/poco_data_v5.csv'
OUTPUT_DB = BASE_DIR / 'db/poco_analysis.db'
K7_DB     = BASE_DIR / 'db/マルハンメガシティ2000-蒲田7.db'
K1_DB     = BASE_DIR / 'db/マルハンメガシティ2000-蒲田1.db'

HALL_CONFIG = {
    'K7': {
        'db_path':      K7_DB,
        'strategy_col': 'kamata7_weekday_strategy',
        'diff_col':     'kamata7_diff',
        'targets_col':  'kamata7_full_half_normalized',
    },
    'K1': {
        'db_path':      K1_DB,
        'strategy_col': 'kamata1_weekday_strategy',
        'diff_col':     'kamata1_diff',
        'targets_col':  'kamata1_full_half_normalized',
    },
}

WEEKDAYS_JP = ['月', '火', '水', '木', '金', '土', '日']

# machine_master によるセグメント条件
N_COND = '(mm.jug_flag=1 OR mm.hana_flag=1 OR mm.oki_flag=1)'   # ノーマル系
A_COND = ('(mm.jug_flag=0 AND mm.hana_flag=0 '
           'AND mm.oki_flag=0 AND mm.bt_flag=0)')                  # AT/スマスロ系


# ─────────────────────────────────────────────
# 曜日仕掛けパーサー
# ─────────────────────────────────────────────

def parse_strategy(raw) -> tuple:
    """
    Returns (strategy_type, strategy_digits_str, is_calculable)
    strategy_type: 末尾 / 全台 / 末尾ゾロ目 / 角 / 列 / 並び / 機種イチ / 不明
    strategy_digits_str: カンマ区切り数字文字列 e.g. "3,7"  (末尾のみ)
    is_calculable: bool
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ('不明', None, False)

    s = str(raw).strip()

    # ── 全機種全台
    if '全機種全台' in s:
        return ('全台', None, True)

    # ── 並び（末尾数字が取れれば計算可能）
    if '並び' in s:
        digits = _extract_narabi_digits(s)
        window = _get_narabi_window(s)
        if digits:
            # strategy_digits に "digits|window" 形式で格納
            return ('並び', f"{','.join(digits)}|{window}", True)
        return ('並び', None, False)

    # ── 列仕掛け
    if '列' in s:
        return ('列', None, False)

    # ── 末尾ゾロ目（末尾 + ゾロ目 or 単独ゾロ目）
    if 'ゾロ目' in s:
        return ('末尾ゾロ目', None, True)

    # ── 末尾N （角を含まない場合のみ）
    if '末尾' in s and '角' not in s:
        digits = _extract_suei_digits(s)
        if digits:
            return ('末尾', ','.join(digits), True)
        # 末尾仕掛け等で数字が取れない場合
        return ('末尾', None, False)

    # ── 角仕掛け
    if '角' in s:
        return ('角', None, False)

    # ── 機種イチ以上
    if '機種イチ' in s or '機種一' in s:
        return ('機種イチ', None, False)

    return ('不明', None, False)


def _extract_narabi_digits(s: str) -> list:
    """
    並び系文字列から末尾指定の数字を抽出。
    対応例:
      末尾3絡み              → ['3']
      ジャグラー末尾3絡み、AT末尾8絡み → ['3','8']
      末尾2or5絡み           → ['2','5']
      末尾6〜0               → ['6','0']  (両端)
      末尾4・7絡み           → ['4','7']
      末尾9,0,1              → ['9','0','1']
    """
    digits = []

    # パターン1: 末尾直後の数字（最も一般的）
    for m in re.finditer(r'末尾(\d)', s):
        digits.append(m.group(1))

    # パターン2: 末尾N〜M の後半 M
    for m in re.finditer(r'末尾\d[〜~](\d)', s):
        digits.append(m.group(1))

    # パターン3: 末尾Nor M の後半 M
    for m in re.finditer(r'末尾\dor(\d)', s):
        digits.append(m.group(1))

    # パターン4: 末尾N・M の後半 M
    for m in re.finditer(r'末尾\d[・,](\d)', s):
        digits.append(m.group(1))

    # パターン5: 「ジャグN」「他N」形式（N=ノーマル起点・A=AT起点が別々に書かれる）
    # 例: 並び（ジャグ1、他5絡み）→ ['1','5']
    #     並び（ジャグ6、他1絡み）→ ['6','1']
    for m in re.finditer(r'(?:ジャグ|他)(\d)', s):
        digits.append(m.group(1))

    # 重複除去（出現順を保持）
    seen = set()
    result = []
    for d in digits:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return result


def _get_narabi_window(s: str) -> int:
    """
    並びの台数からウィンドウサイズを決定。
    3台並び → 2 (±2)
    4台並び → 3 (±3)
    5台並び → 4 (±4)
    デフォルト → 2
    """
    # 最大の台数を使う（例: "+4台並び" があれば4を採用）
    matches = re.findall(r'(\d)台並び', s)
    if matches:
        max_n = max(int(m) for m in matches)
        return max_n - 1
    return 2  # デフォルト: 3台並び相当


def _extract_suei_digits(s: str) -> list:
    """
    文字列から末尾指定の数字（0-9）を抽出。
    対応パターン例:
      末尾3と7       → ['3','7']
      末尾→末尾1・6  → ['1','6']
      末尾（0と4）   → ['0','4']
      末尾0(AT)末尾5 → ['0','5']
      水曜日→末尾→ジャグラー末尾0、その他機種末尾5 → ['0','5']
    """
    digits = []

    # パターン1: 末尾の直後（間に0〜6文字の非数字）に続く数字
    for m in re.finditer(r'末尾[^\d]{0,6}?(\d)', s):
        digits.append(m.group(1))

    # パターン2: 括弧内の "Nと M" または "N・M" 形式
    for m in re.finditer(r'[（(](\d)[とと・](\d)', s):
        digits.append(m.group(1))
        digits.append(m.group(2))

    # 重複除去（出現順を保持）
    seen = set()
    result = []
    for d in digits:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return result


# ─────────────────────────────────────────────
# DB クエリヘルパー
# ─────────────────────────────────────────────

def get_total_diff(conn, date: str):
    row = conn.execute(
        'SELECT SUM(diff_coins_normalized) FROM machine_detailed_results WHERE date=?',
        (date,)
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def get_strategy_performance(conn, date: str, s_type: str, s_digits):
    """
    Returns (avg_diff, win_rate, machine_count) or (None, None, None)
    """
    base = '''
        SELECT
            AVG(diff_coins_normalized),
            CAST(SUM(CASE WHEN diff_coins_normalized > 0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*),
            COUNT(*)
        FROM machine_detailed_results
        WHERE date=?
    '''
    if s_type == '全台':
        row = conn.execute(base, (date,)).fetchone()

    elif s_type == '末尾' and s_digits:
        digits = [d.strip() for d in s_digits.split(',')]
        placeholders = ','.join(['?' for _ in digits])
        q = base + f' AND last_digit IN ({placeholders})'
        row = conn.execute(q, (date, *digits)).fetchone()

    elif s_type == '末尾ゾロ目':
        row = conn.execute(base + ' AND is_zorome=1', (date,)).fetchone()

    elif s_type == '並び' and s_digits and '|' in s_digits:
        # "digits|window" 形式をパース
        digits_part, window_part = s_digits.rsplit('|', 1)
        digits  = [d.strip() for d in digits_part.split(',')]
        window  = int(window_part)
        placeholders = ','.join(['?' for _ in digits])
        q = f'''
            SELECT
                AVG(m.diff_coins_normalized),
                CAST(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*),
                COUNT(*)
            FROM machine_detailed_results m
            WHERE m.date = ?
            AND EXISTS (
                SELECT 1 FROM machine_detailed_results anchor
                WHERE anchor.date = ?
                  AND anchor.last_digit IN ({placeholders})
                  AND ABS(m.machine_number - anchor.machine_number) <= ?
            )
        '''
        row = conn.execute(q, (date, date, *digits, window)).fetchone()

    else:
        return None, None, None

    if row and row[2] and row[2] > 0:
        return row[0], row[1], row[2]
    return None, None, None


def get_best_triple(conn, date: str, seg_cond: str) -> tuple:
    """
    全10連番トリプル（0,1,2 ～ 9,0,1）の中で avg_diff が最大のものを返す。
    ぽこテキストに依存しない DB 実績からの逆算推定値。

    Returns (triple_str, avg_diff) e.g. ("8,9,0", 1200.5)
    triple_str の起点は最大ギャップの直後の数字（循環起点）。
    """
    q = f'''
        SELECT m.last_digit, AVG(m.diff_coins_normalized) AS avg_diff
        FROM machine_detailed_results m
        JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
        WHERE m.date=? AND {seg_cond}
        GROUP BY m.last_digit
    '''
    rows = conn.execute(q, (date,)).fetchall()
    if len(rows) < 3:
        return None, None

    perf = {r[0]: r[1] for r in rows}  # last_digit(str) -> avg_diff

    best_triple = None
    best_avg    = None
    for start in range(10):
        triple = [str(start), str((start + 1) % 10), str((start + 2) % 10)]
        if not all(d in perf for d in triple):
            continue  # 3桁すべてにデータが必要
        avg = sum(perf[d] for d in triple) / 3
        if best_avg is None or avg > best_avg:
            best_avg   = avg
            best_triple = ','.join(triple)

    return best_triple, best_avg


def get_machine_performance(conn, date: str, machine_name: str):
    """
    Returns (avg_diff, win_rate, avg_games, machine_count)
    """
    q = '''
        SELECT
            AVG(diff_coins_normalized),
            CAST(SUM(CASE WHEN diff_coins_normalized > 0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*),
            AVG(games_normalized),
            COUNT(*)
        FROM machine_detailed_results
        WHERE date=? AND machine_name=?
    '''
    row = conn.execute(q, (date, machine_name)).fetchone()
    if row and row[3] and row[3] > 0:
        return row[0], row[1], row[2], row[3]
    return None, None, None, 0


# ─────────────────────────────────────────────
# DB 構築メイン
# ─────────────────────────────────────────────

def build_poco_analysis_db():
    poco_df = pd.read_csv(POCO_CSV)
    poco_df['date'] = poco_df['date'].astype(str)

    # 既存DBを削除して再作成
    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()
    out_conn = sqlite3.connect(OUTPUT_DB)

    out_conn.executescript('''
        CREATE TABLE poco_announcements (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            date                    TEXT NOT NULL,
            hall                    TEXT NOT NULL,
            weekday_jp              TEXT,
            dd                      INTEGER,
            is_event_day            INTEGER,
            is_zorome_date          INTEGER,
            total_diff              INTEGER,
            weekday_strategy_raw    TEXT,
            strategy_type           TEXT,
            strategy_digits         TEXT,
            is_calculable           INTEGER,
            strategy_avg_diff       REAL,
            strategy_win_rate       REAL,
            strategy_machine_count  INTEGER,
            est_n_triple            TEXT,
            est_n_triple_avg_diff   REAL,
            est_a_triple            TEXT,
            est_a_triple_avg_diff   REAL,
            UNIQUE(date, hall)
        );

        CREATE TABLE poco_targets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT NOT NULL,
            hall          TEXT NOT NULL,
            machine_name  TEXT NOT NULL,
            avg_diff      REAL,
            win_rate      REAL,
            avg_games     REAL,
            machine_count INTEGER,
            UNIQUE(date, hall, machine_name)
        );
    ''')

    hall_conns = {h: sqlite3.connect(cfg['db_path']) for h, cfg in HALL_CONFIG.items()}

    ann_rows = []
    tgt_rows = []

    for _, row in poco_df.iterrows():
        date           = row['date']
        dd             = int(row['day'])
        is_ev          = int(row['is_event_day'])
        is_zorome_date = 1 if dd in [11, 22] else 0
        dt             = datetime.strptime(date, '%Y%m%d')
        wday_jp        = WEEKDAYS_JP[dt.weekday()]

        for hall, cfg in HALL_CONFIG.items():
            conn = hall_conns[hall]

            # ── total_diff（poco NaN → DB から補完）
            poco_diff  = row[cfg['diff_col']]
            total_diff = (
                int(poco_diff) if pd.notna(poco_diff)
                else get_total_diff(conn, date)
            )

            # ── 曜日仕掛けパース
            raw_strat           = row[cfg['strategy_col']]
            s_type, s_digits, is_calc = parse_strategy(raw_strat)

            # ── 曜日仕掛け実績
            s_avg_diff = s_win_rate = s_mc = None
            if is_calc:
                s_avg_diff, s_win_rate, s_mc = get_strategy_performance(
                    conn, date, s_type, s_digits
                )

            # ── 逆算推定トリプル（ぽこテキスト非依存・全日付で計算）
            est_n_triple, est_n_avg = get_best_triple(conn, date, N_COND)
            est_a_triple, est_a_avg = get_best_triple(conn, date, A_COND)

            ann_rows.append((
                date, hall, wday_jp, dd, is_ev, is_zorome_date,
                total_diff,
                str(raw_strat) if pd.notna(raw_strat) else None,
                s_type, s_digits, int(is_calc),
                s_avg_diff, s_win_rate, s_mc,
                est_n_triple, est_n_avg,
                est_a_triple, est_a_avg,
            ))

            # ── 発表機種ターゲット
            targets_raw = row[cfg['targets_col']]
            if pd.notna(targets_raw) and str(targets_raw).strip():
                for mname in str(targets_raw).split('、'):
                    mname = mname.strip()
                    if not mname:
                        continue
                    avg_d, wr, avg_g, mc = get_machine_performance(conn, date, mname)
                    if mc > 0:
                        tgt_rows.append((date, hall, mname, avg_d, wr, avg_g, mc))

    # ── バルクインサート
    out_conn.executemany(
        'INSERT OR IGNORE INTO poco_announcements VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        ann_rows
    )
    out_conn.executemany(
        'INSERT OR IGNORE INTO poco_targets VALUES (NULL,?,?,?,?,?,?,?)',
        tgt_rows
    )
    out_conn.commit()

    # ── サマリー表示
    print('=' * 52)
    print('poco_analysis.db 構築完了')
    print('=' * 52)

    ann_total  = out_conn.execute('SELECT COUNT(*) FROM poco_announcements').fetchone()[0]
    tgt_total  = out_conn.execute('SELECT COUNT(*) FROM poco_targets').fetchone()[0]
    calc_total = out_conn.execute(
        'SELECT COUNT(*) FROM poco_announcements WHERE is_calculable=1'
    ).fetchone()[0]
    diff_filled = out_conn.execute(
        'SELECT COUNT(*) FROM poco_announcements WHERE total_diff IS NOT NULL'
    ).fetchone()[0]

    print(f'poco_announcements  : {ann_total} 行')
    print(f'  is_calculable=1   : {calc_total} 行 ({calc_total/ann_total*100:.1f}%)')
    print(f'  total_diff 補完後 : {diff_filled} / {ann_total} 行')
    print(f'poco_targets        : {tgt_total} 行')

    print('\n=== strategy_type 分布（K7/K1 別）===')
    rows = out_conn.execute('''
        SELECT hall, strategy_type, COUNT(*) as n,
               ROUND(AVG(strategy_avg_diff)) as avg_diff,
               ROUND(AVG(strategy_win_rate)*100, 1) as win_rate_pct
        FROM poco_announcements
        GROUP BY hall, strategy_type
        ORDER BY hall, n DESC
    ''').fetchall()
    print(f'{"hall":<4} {"type":<12} {"n":>4} {"avg_diff":>9} {"win_rate%":>10}')
    print('-' * 44)
    for r in rows:
        avg_d = f'{r[3]:+.0f}' if r[3] is not None else '     -'
        wr    = f'{r[4]:.1f}%' if r[4] is not None else '      -'
        print(f'{r[0]:<4} {r[1]:<12} {r[2]:>4} {avg_d:>9} {wr:>10}')

    print('\n=== 逆算推定トリプル（est_*_triple）サンプル ===')
    sample_rows = out_conn.execute('''
        SELECT hall, date, strategy_type, strategy_digits,
               est_n_triple, ROUND(est_n_triple_avg_diff) as n_avg,
               est_a_triple, ROUND(est_a_triple_avg_diff) as a_avg
        FROM poco_announcements
        WHERE est_n_triple IS NOT NULL
        ORDER BY hall, date
        LIMIT 8
    ''').fetchall()
    print(f'{"hall":<3} {"date":<9} {"poco_type":<8} {"poco_digits":<12} '
          f'{"N_triple":<9} {"N_avg":>7}  {"A_triple":<9} {"A_avg":>7}')
    print('-' * 72)
    for r in sample_rows:
        pd_str = str(r[3]) if r[3] else '-'
        print(f'{r[0]:<3} {r[1]:<9} {r[2]:<8} {pd_str:<12} '
              f'{str(r[4]):<9} {r[5]:>7}  {str(r[6]):<9} {r[7]:>7}')

    est_n_ok = out_conn.execute(
        'SELECT COUNT(*) FROM poco_announcements WHERE est_n_triple IS NOT NULL'
    ).fetchone()[0]
    est_a_ok = out_conn.execute(
        'SELECT COUNT(*) FROM poco_announcements WHERE est_a_triple IS NOT NULL'
    ).fetchone()[0]
    print(f'\nest_n_triple 計算済: {est_n_ok} / {ann_total} 行')
    print(f'est_a_triple 計算済: {est_a_ok} / {ann_total} 行')

    print(f'\n出力先: {OUTPUT_DB}')

    out_conn.close()
    for c in hall_conns.values():
        c.close()


if __name__ == '__main__':
    build_poco_analysis_db()
