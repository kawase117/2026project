"""
ぽこ仕掛け内容の的中率分析
仕掛け機種が実際に高差枚だったかを top-k ランキングで評価
"""
import pandas as pd
import sqlite3
from pathlib import Path
import re
from datetime import datetime

print("=" * 100)
print("POCO Accuracy Analysis: Facility Content vs Actual DB Results")
print("=" * 100)

# === Data Load ===
poco_df = pd.read_csv(Path("docs/poco_data_extracted.csv"))
poco_df['date'] = poco_df['date'].astype(str)

conn_7 = sqlite3.connect("db/マルハンメガシティ2000-蒲田7.db")
conn_1 = sqlite3.connect("db/マルハンメガシティ2000-蒲田1.db")

db_7_detailed = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn_7)
db_1_detailed = pd.read_sql_query("SELECT * FROM machine_detailed_results", conn_1)

conn_7.close()
conn_1.close()

db_7_detailed['date'] = db_7_detailed['date'].astype(str)
db_1_detailed['date'] = db_1_detailed['date'].astype(str)

print(f"\nData loaded:")
print(f"  Poco reports: {len(poco_df)}")
print(f"  DB Kamata7: {len(db_7_detailed)} machine records")
print(f"  DB Kamata1: {len(db_1_detailed)} machine records")

# === Machine name normalization ===
def normalize_machine_name(name):
    """Machine name normalization"""
    if not name or pd.isna(name):
        return None

    name = str(name).strip()

    # Hokuto series
    if 'hokuto' in name.lower() or 'hokuton' in name.lower():
        return 'hokuto'

    # Jaggler series
    if 'jaggler' in name.lower() or 'jagura' in name.lower():
        return 'jaggler'

    # Return as-is for others
    return name

# === Parse poco content: extract machine names ===
def parse_poco_content(content):
    """
    Extract machine names from poco content
    Example: "all-magireco, monhan" -> ["magireco", "monhan"]
    """
    if not content or pd.isna(content):
        return []

    content = str(content).strip()

    # Special case: all machines
    if 'all' in content.lower():
        return ['all']

    # Split by comma/period
    parts = re.split(r'[,、]', content)
    machines = []

    for part in parts:
        part = part.strip()
        # Extract after arrow
        if '→' in part:
            part = part.split('→')[-1].strip()

        # Remove parenthetical text
        part = re.sub(r'[（\(].*?[）\)]', '', part)
        part = part.strip()

        # Exclude numbers/floor info
        if part and not re.match(r'^[0-9F層階]+$', part):
            normalized = normalize_machine_name(part)
            if normalized:
                machines.append(normalized)

    return machines if machines else ['unknown']

# === Analyze by hall ===
def analyze_hall(poco_data, db_detailed, hall_name, content_col_suffix):
    """Analyze accuracy for each hall"""

    print(f"\n{'='*100}")
    print(f"### {hall_name} Analysis ###")
    print(f"{'='*100}")

    # Filter poco data
    if '_7' in content_col_suffix:
        poco_hall = poco_data[poco_data['kamata7_diff'].notna()].copy()
        content_col = 'kamata7_content'
    else:
        poco_hall = poco_data[poco_data['kamata1_diff'].notna()].copy()
        content_col = 'kamata1_content'

    print(f"\nPoco reports: {len(poco_hall)}")

    if len(poco_hall) == 0:
        print("No data for this hall")
        return None

    # Parse machine names
    poco_hall['machines_reported'] = poco_hall[content_col].apply(parse_poco_content)

    # Analyze by date
    accuracy_results = []

    for _, row in poco_hall.iterrows():
        date = row['date']
        reported_machines = row['machines_reported']

        # Get DB records for this date
        db_day = db_detailed[db_detailed['date'] == date]

        if db_day.empty:
            continue

        # Calculate machine ranking by total diff
        machine_by_diff = db_day.groupby('machine_name')['diff_coins_normalized'].sum().reset_index()
        machine_by_diff = machine_by_diff.sort_values('diff_coins_normalized', ascending=False)

        # Top-k rankings
        top_machines = machine_by_diff['machine_name'].head(10).tolist()
        top3 = machine_by_diff['machine_name'].head(3).tolist()
        top5 = machine_by_diff['machine_name'].head(5).tolist()

        # Count hits (excluding 'all' and 'unknown')
        hits_top3 = sum(1 for m in reported_machines if m in top3 and m != 'all' and m != 'unknown')
        hits_top5 = sum(1 for m in reported_machines if m in top5 and m != 'all' and m != 'unknown')
        hits_top10 = sum(1 for m in reported_machines if m in top_machines and m != 'all' and m != 'unknown')

        reported_count = sum(1 for m in reported_machines if m != 'all' and m != 'unknown')

        accuracy_results.append({
            'date': date,
            'reported_machines': ', '.join(reported_machines),
            'reported_count': reported_count,
            'top3_machines': ', '.join(top3),
            'top5_machines': ', '.join(top5),
            'hits_top3': hits_top3,
            'hits_top5': hits_top5,
            'hits_top10': hits_top10,
            'accuracy_top3': (hits_top3 / reported_count * 100) if reported_count > 0 else 0,
            'accuracy_top5': (hits_top5 / reported_count * 100) if reported_count > 0 else 0,
            'accuracy_top10': (hits_top10 / reported_count * 100) if reported_count > 0 else 0,
        })

    df_accuracy = pd.DataFrame(accuracy_results)

    if df_accuracy.empty:
        print("No matching dates between poco and DB")
        return None

    # === Results Summary ===
    print(f"\nSample reports (first 10):")
    for idx, (_, row) in enumerate(df_accuracy.head(10).iterrows()):
        print(f"\n  {row['date']}")
        print(f"    Reported: {row['reported_machines']}")
        print(f"    Top-3:    {row['top3_machines']}")
        print(f"    Hit top-3: {row['hits_top3']}/{row['reported_count']} ({row['accuracy_top3']:.1f}%)")
        print(f"    Hit top-5: {row['hits_top5']}/{row['reported_count']} ({row['accuracy_top5']:.1f}%)")

    # === Summary Statistics ===
    print(f"\n### Accuracy Statistics ###")
    print(f"\nTop-3 ranking accuracy:")
    print(f"  Mean:   {df_accuracy['accuracy_top3'].mean():.1f}%")
    print(f"  Median: {df_accuracy['accuracy_top3'].median():.1f}%")
    print(f"  Min:    {df_accuracy['accuracy_top3'].min():.1f}%")
    print(f"  Max:    {df_accuracy['accuracy_top3'].max():.1f}%")

    print(f"\nTop-5 ranking accuracy:")
    print(f"  Mean:   {df_accuracy['accuracy_top5'].mean():.1f}%")
    print(f"  Median: {df_accuracy['accuracy_top5'].median():.1f}%")
    print(f"  Min:    {df_accuracy['accuracy_top5'].min():.1f}%")
    print(f"  Max:    {df_accuracy['accuracy_top5'].max():.1f}%")

    print(f"\nTop-10 ranking accuracy:")
    print(f"  Mean:   {df_accuracy['accuracy_top10'].mean():.1f}%")
    print(f"  Median: {df_accuracy['accuracy_top10'].median():.1f}%")

    # === Distribution ===
    print(f"\n### Accuracy Distribution (Top-3) ###")
    print(f"  100% (all hit): {(df_accuracy['accuracy_top3'] == 100).sum()} days")
    print(f"  50-99%:         {((df_accuracy['accuracy_top3'] >= 50) & (df_accuracy['accuracy_top3'] < 100)).sum()} days")
    print(f"  1-49%:          {((df_accuracy['accuracy_top3'] > 0) & (df_accuracy['accuracy_top3'] < 50)).sum()} days")
    print(f"  0% (miss):      {(df_accuracy['accuracy_top3'] == 0).sum()} days")

    return df_accuracy

# === Run Analysis ===
results_7 = analyze_hall(poco_df, db_7_detailed, 'Kamata7', '_7')
results_1 = analyze_hall(poco_df, db_1_detailed, 'Kamata1', '_1')

# === Final Conclusion ===
print(f"\n{'='*100}")
print("CONCLUSION")
print(f"{'='*100}")

if results_7 is not None:
    print(f"\nKamata7:")
    print(f"  Samples analyzed: {len(results_7)}")
    print(f"  Average top-5 accuracy: {results_7['accuracy_top5'].mean():.1f}%")
    print(f"  Days with 50%+ top-5 accuracy: {(results_7['accuracy_top5'] >= 50).sum()} / {len(results_7)}")
    interpretation_7 = "MODERATE" if results_7['accuracy_top5'].mean() > 40 else "LOW"
    print(f"  Interpretation: {interpretation_7} (top-5 avg {results_7['accuracy_top5'].mean():.1f}%)")

if results_1 is not None:
    print(f"\nKamata1:")
    print(f"  Samples analyzed: {len(results_1)}")
    print(f"  Average top-5 accuracy: {results_1['accuracy_top5'].mean():.1f}%")
    print(f"  Days with 50%+ top-5 accuracy: {(results_1['accuracy_top5'] >= 50).sum()} / {len(results_1)}")
    interpretation_1 = "MODERATE" if results_1['accuracy_top5'].mean() > 40 else "LOW"
    print(f"  Interpretation: {interpretation_1} (top-5 avg {results_1['accuracy_top5'].mean():.1f}%)")

print(f"\n{'='*100}")
