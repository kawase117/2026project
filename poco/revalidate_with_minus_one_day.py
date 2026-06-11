"""
モグ玄データを -1day シフトで再検証
前セッションの発見：モグ玄機種 vs ぽこ機種の一致率が -1day で 80% ➜ 日付ズレは「前日報告」が正しい可能性
"""
import pandas as pd
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

print("=" * 100)
print("RE-VALIDATION: Mogendo with -1day shift (前日報告 hypothesis)")
print("=" * 100)

# === Data Load ===
mogendo_dir = Path("docs/モグ玄データ抽出")
summary_df = pd.read_csv(mogendo_dir / "kamata_summary.csv")
detail_df = pd.read_csv(mogendo_dir / "kamata_detail.csv")
poco_df = pd.read_csv(Path("docs/poco_data_extracted.csv"))

# Normalize dates
summary_df['date'] = summary_df['日付'].str.replace('.', '')
detail_df['date'] = detail_df['日付'].str.replace('.', '')

# Load DB
conn_7 = sqlite3.connect("db/マルハンメガシティ2000-蒲田7.db")
db_7 = pd.read_sql_query("SELECT * FROM daily_hall_summary", conn_7)
conn_7.close()

db_7['date'] = db_7['date'].astype(str)
poco_df['date'] = poco_df['date'].astype(str)

# === Step 1: Shift Summary by -1 day ===
print("\n### Step 1: Shift Mogendo Summary by -1 day ###")

summary_7 = summary_df[summary_df['店舗'] == '蒲田7'].copy()
detail_7 = detail_df[detail_df['店舗'] == '蒲田7'].copy()

print(f"Original Summary dates: {len(summary_7)} entries")

def shift_date(date_str, offset=-1):
    """Shift YYYYMMDD format date by offset days"""
    try:
        d = datetime.strptime(str(date_str), "%Y%m%d")
        shifted = d + timedelta(days=offset)
        return shifted.strftime("%Y%m%d")
    except:
        return None

summary_7['shifted_date'] = summary_7['date'].apply(lambda d: shift_date(d, offset=-1))
print(f"Sample shifts:")
for i, row in summary_7.head(5).iterrows():
    print(f"  {row['date']} → {row['shifted_date']}")

# === Step 2: Match Summary (shifted) with Detail ===
print("\n### Step 2: Match Summary (shifted) with Detail ###")

detail_7_daily = detail_7.groupby('date')['差枚'].sum().reset_index()
detail_7_daily.columns = ['date', 'detail_total_diff']

matches_before = []
matches_after = []

for _, row in summary_7.iterrows():
    s_date = row['date']
    s_shifted = row['shifted_date']
    s_diff = row['対象差枚']

    # Before shift
    for shift_offset in [0, 1, -1]:
        shifted_for_match = str(int(s_date) + shift_offset).zfill(8)
        match = detail_7_daily[detail_7_daily['date'] == shifted_for_match]
        if not match.empty:
            d_diff = match['detail_total_diff'].values[0]
            error_pct = abs(d_diff - s_diff) / s_diff * 100 if s_diff > 0 else 0
            matches_before.append({
                'summary_date': s_date,
                'summary_diff': s_diff,
                'detail_date': shifted_for_match,
                'detail_diff': d_diff,
                'shift': shift_offset,
                'error_pct': error_pct
            })
            break

    # After -1day shift
    for shift_offset in [0, 1, -1]:
        shifted_for_match = str(int(s_shifted) + shift_offset).zfill(8)
        match = detail_7_daily[detail_7_daily['date'] == shifted_for_match]
        if not match.empty:
            d_diff = match['detail_total_diff'].values[0]
            error_pct = abs(d_diff - s_diff) / s_diff * 100 if s_diff > 0 else 0
            matches_after.append({
                'summary_date': s_date,
                'shifted_date': s_shifted,
                'summary_diff': s_diff,
                'detail_date': shifted_for_match,
                'detail_diff': d_diff,
                'shift_from_shifted': shift_offset,
                'error_pct': error_pct
            })
            break

df_before = pd.DataFrame(matches_before)
df_after = pd.DataFrame(matches_after)

print(f"\nBEFORE -1day shift:")
if not df_before.empty:
    print(f"  Matched: {len(df_before)} / {len(summary_7)}")
    print(f"  Error rate (mean): {df_before['error_pct'].mean():.1f}%")
    print(f"  Error rate (range): {df_before['error_pct'].min():.1f}% ~ {df_before['error_pct'].max():.1f}%")
    shift_dist = df_before['shift'].value_counts().sort_index()
    print(f"  Shift dist: {dict(shift_dist)}")

print(f"\nAFTER -1day shift:")
if not df_after.empty:
    print(f"  Matched: {len(df_after)} / {len(summary_7)}")
    print(f"  Error rate (mean): {df_after['error_pct'].mean():.1f}%")
    print(f"  Error rate (range): {df_after['error_pct'].min():.1f}% ~ {df_after['error_pct'].max():.1f}%")
    shift_dist_after = df_after['shift_from_shifted'].value_counts().sort_index()
    print(f"  Shift dist (from shifted): {dict(shift_dist_after)}")

# === Step 3: Examples ===
print("\n### Step 3: Sample Comparisons ###")
print("\nBest matches (BEFORE):")
if not df_before.empty:
    for i, row in df_before.nsmallest(5, 'error_pct').iterrows():
        print(f"  {row['summary_date']}: {row['summary_diff']:>10,.0f} vs Detail({row['detail_date']})={row['detail_diff']:>10,.0f} >> {row['error_pct']:>6.1f}%")

print("\nBest matches (AFTER -1day):")
if not df_after.empty:
    for i, row in df_after.nsmallest(5, 'error_pct').iterrows():
        print(f"  {row['summary_date']} → {row['shifted_date']}: {row['summary_diff']:>10,.0f} vs Detail({row['detail_date']})={row['detail_diff']:>10,.0f} >> {row['error_pct']:>6.1f}%")

# === Step 4: Conclusion ===
print("\n" + "=" * 100)
print("CONCLUSION")
print("=" * 100)

improvement_before = (len(matches_before) / len(summary_7) * 100) if matches_before else 0
improvement_after = (len(matches_after) / len(summary_7) * 100) if matches_after else 0

print(f"\nDate-to-Detail Matching Rate:")
print(f"  BEFORE: {improvement_before:.1f}% ({len(matches_before)}/{len(summary_7)})")
print(f"  AFTER:  {improvement_after:.1f}% ({len(matches_after)}/{len(summary_7)})")

if not df_before.empty and not df_after.empty:
    error_improvement = df_before['error_pct'].mean() - df_after['error_pct'].mean()
    print(f"\nError Rate Improvement:")
    print(f"  Before: {df_before['error_pct'].mean():.1f}%")
    print(f"  After:  {df_after['error_pct'].mean():.1f}%")
    print(f"  Delta:  {error_improvement:.1f}%")

if improvement_after > improvement_before and not df_after.empty and df_after['error_pct'].mean() < df_before['error_pct'].mean():
    print(f"\nOK -1day shift IMPROVES alignment by {improvement_after - improvement_before:.1f}% matching and {df_before['error_pct'].mean() - df_after['error_pct'].mean():.1f}% error reduction")
    print(f"OK HYPOTHESIS CONFIRMED: Mogendo reports with -1day shift (zenjitsu-houkoku)")
elif improvement_after >= improvement_before:
    print(f"\nOK -1day shift maintains or improves alignment")
else:
    print(f"\nNG -1day shift does NOT improve matching")
    print(f"NG Hypothesis NOT supported by data - BEFORE shift is better")

print("\n" + "=" * 100)
