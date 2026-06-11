"""
ステルス機種 vs 対象機種 比較分析
- 差枚、G数、勝率、台数で一覧表示
- 全期間 vs 最近2ヶ月（トレンド）を比較
- ステルス機種がマグレか本物かを判別
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3
import pandas as pd
import numpy as np

# ============================================================
# 設定
# ============================================================
BASE = r"C:/Users/apto117/Documents/pachinko-analyzer/src/2026project"
POCO_CSV = f"{BASE}/docs/poco/poco_data_v5.csv"  # 最新正規化済み（v5）
DB_K7 = f"{BASE}/db/マルハンメガシティ2000-蒲田7.db"
DB_K1 = f"{BASE}/db/マルハンメガシティ2000-蒲田1.db"

COLOR_MACHINES = {'スーパービンゴネオ', 'ネオプラネット', 'チバリヨ2プラス'}
TOP_N = 3
RECENT_CUTOFF = "20260401"  # 最近2ヶ月

# ============================================================
# ユーティリティ
# ============================================================
def parse_machines(cell):
    if pd.isna(cell) or str(cell).strip() == '':
        return []
    return [m.strip() for m in str(cell).split('、') if m.strip()]

def build_summary(conn, machines, date_filter=None):
    if not machines:
        return pd.DataFrame()
    placeholders = ','.join(['?'] * len(machines))
    date_cond = f"AND date >= '{date_filter}'" if date_filter else ""
    query = f"""
    SELECT
        machine_name AS name,
        COUNT(DISTINCT date) AS days,
        ROUND(AVG(machine_count), 1) AS avg_cnt,
        ROUND(AVG(avg_diff_coins), 0) AS avg_diff,
        ROUND(AVG(win_rate) * 100, 1) AS win_pct,
        ROUND(SUM(total_games) / 1000.0, 1) AS total_g_k
    FROM daily_machine_type_summary
    WHERE machine_name IN ({placeholders})
    {date_cond}
    GROUP BY machine_name
    ORDER BY avg_diff DESC
    """
    df = pd.read_sql_query(query, conn, params=machines)
    df = df.rename(columns={
        'name': '機種名',
        'days': '出現日数',
        'avg_cnt': '平均台数',
        'avg_diff': '1台平均差枚',
        'win_pct': '平均勝率%',
        'total_g_k': '総G数K',
    })
    return df

def get_daily_top(conn, top_n=3):
    query = """
    SELECT date, machine_name, avg_diff_coins, machine_count, win_rate
    FROM daily_machine_type_summary
    WHERE machine_count >= 2
    ORDER BY date, avg_diff_coins DESC
    """
    df = pd.read_sql_query(query, conn)
    df['rank'] = df.groupby('date')['avg_diff_coins'].rank(ascending=False, method='first')
    return df[df['rank'] <= top_n].copy()

# ============================================================
# メイン
# ============================================================
poco = pd.read_csv(POCO_CSV, encoding='utf-8-sig')
poco['date'] = poco['date'].astype(str)

# ----- Step 1: ぽこ報告機種を収集 -----
k7_targets = set()
k1_targets = set()
poco_k7_by_date = {}
poco_k1_by_date = {}

for _, row in poco.iterrows():
    d = str(row['date'])
    k7 = set(parse_machines(row.get('kamata7_full_half_normalized', ''))) - COLOR_MACHINES
    k1 = set(parse_machines(row.get('kamata1_full_half_normalized', ''))) - COLOR_MACHINES
    k7_targets.update(k7)
    k1_targets.update(k1)
    poco_k7_by_date[d] = k7
    poco_k1_by_date[d] = k1

# ----- Step 2: 日別TOP機種からステルス判定 -----
print("DB読み込み中...")
conn7 = sqlite3.connect(DB_K7)
conn1 = sqlite3.connect(DB_K1)

k7_top = get_daily_top(conn7, TOP_N)
k1_top = get_daily_top(conn1, TOP_N)

def find_stealth(top_df, poco_by_date):
    records = []
    for _, row in top_df.iterrows():
        date = str(row['date'])
        machine = row['machine_name']
        if machine in COLOR_MACHINES:
            continue
        if date in poco_by_date and len(poco_by_date[date]) > 0:
            if machine not in poco_by_date[date]:
                records.append({
                    'date': date,
                    'machine_name': machine,
                    'avg_diff': row['avg_diff_coins'],
                    'machine_count': row['machine_count'],
                })
    return pd.DataFrame(records) if records else pd.DataFrame()

k7_stealth_df = find_stealth(k7_top, poco_k7_by_date)
k1_stealth_df = find_stealth(k1_top, poco_k1_by_date)

MIN_APPEAR = 3
k7_stealth_names = []
k1_stealth_names = []

if not k7_stealth_df.empty:
    cnt = k7_stealth_df['machine_name'].value_counts()
    k7_stealth_names = cnt[cnt >= MIN_APPEAR].index.tolist()

if not k1_stealth_df.empty:
    cnt = k1_stealth_df['machine_name'].value_counts()
    k1_stealth_names = cnt[cnt >= MIN_APPEAR].index.tolist()

# ============================================================
# Step 3: 表示
# ============================================================
def display_table(title, conn, machine_list, stealth_df=None):
    print(f"\n{'='*80}")
    print(f"  {title}  (n={len(machine_list)}機種)")
    print('='*80)
    if not machine_list:
        print("  (データなし)")
        return

    all_s = build_summary(conn, machine_list)
    rec_s = build_summary(conn, machine_list, date_filter=RECENT_CUTOFF)

    if all_s.empty:
        print("  (DBに該当データなし)")
        return

    merged = all_s.copy()
    if not rec_s.empty:
        rec_s = rec_s.rename(columns={
            '出現日数': '[近]日数',
            '1台平均差枚': '[近]1台差枚',
            '平均勝率%': '[近]勝率%',
            '総G数K': '[近]総G数K',
            '平均台数': '[近]平均台数',
        })
        merged = merged.merge(rec_s[['機種名','[近]日数','[近]1台差枚','[近]勝率%']], on='機種名', how='left')
        merged['差分(近-全)'] = (merged['[近]1台差枚'] - merged['1台平均差枚']).round(0)

    # ステルス出現回数を追加
    if stealth_df is not None and not stealth_df.empty:
        cnt_all = stealth_df['machine_name'].value_counts().rename('ステルス回数').reset_index()
        cnt_all.columns = ['機種名', 'ステルス回数']

        rec_stealth = stealth_df[stealth_df['date'] >= RECENT_CUTOFF]
        cnt_rec = rec_stealth['machine_name'].value_counts().rename('[近]ステルス').reset_index()
        cnt_rec.columns = ['機種名', '[近]ステルス']

        merged = merged.merge(cnt_all, on='機種名', how='left')
        merged = merged.merge(cnt_rec, on='機種名', how='left')
        merged['[近]ステルス'] = merged['[近]ステルス'].fillna(0).astype(int)
        merged['ステルス回数'] = merged['ステルス回数'].fillna(0).astype(int)
        merged = merged.sort_values('ステルス回数', ascending=False)
    else:
        merged = merged.sort_values('1台平均差枚', ascending=False)

    print(merged.to_string(index=False))

# K7 対象機種
display_table("K7 ぽこ報告機種（対象機種）", conn7, sorted(k7_targets))

# K7 ステルス機種
display_table("K7 ステルス機種（未報告TOP3常連）", conn7, k7_stealth_names, k7_stealth_df)

# K1 対象機種
display_table("K1 ぽこ報告機種（対象機種）", conn1, sorted(k1_targets))

# K1 ステルス機種
display_table("K1 ステルス機種（未報告TOP3常連）", conn1, k1_stealth_names, k1_stealth_df)

# ============================================================
# Step 4: 月別トレンド（ステルス機種）
# ============================================================
all_stealth_names = list(set(k7_stealth_names + k1_stealth_names))
print(f"\n{'='*80}")
print(f"  月別ステルス出現回数（K7+K1合算）")
print('='*80)

combined_stealth = pd.concat([
    k7_stealth_df.assign(hall='K7') if not k7_stealth_df.empty else pd.DataFrame(),
    k1_stealth_df.assign(hall='K1') if not k1_stealth_df.empty else pd.DataFrame()
], ignore_index=True)

if not combined_stealth.empty and all_stealth_names:
    combined_stealth['ym'] = combined_stealth['date'].str[:6]
    filtered = combined_stealth[combined_stealth['machine_name'].isin(all_stealth_names)]
    monthly = filtered.groupby(['machine_name', 'ym']).size().unstack(fill_value=0)
    # 合計列
    monthly['合計'] = monthly.sum(axis=1)
    monthly = monthly.sort_values('合計', ascending=False)
    print(monthly.to_string())

    print("\n※ [近]= 2026-04-01以降（最近2ヶ月）")

conn7.close()
conn1.close()
print("\n完了")
