"""
poco machine name reconciliation with DB
Extract all machine names from poco content and match with DB records
"""
import pandas as pd
import sqlite3
from pathlib import Path
import re

print("=" * 120)
print("POCO Machine Name Reconciliation Analysis")
print("=" * 120)

# === Load DB machine names ===
conn_7 = sqlite3.connect("db/マルハンメガシティ2000-蒲田7.db")
conn_1 = sqlite3.connect("db/マルハンメガシティ2000-蒲田1.db")

db_7_machines = pd.read_sql_query(
    "SELECT DISTINCT machine_name FROM machine_detailed_results ORDER BY machine_name",
    conn_7
)
db_1_machines = pd.read_sql_query(
    "SELECT DISTINCT machine_name FROM machine_detailed_results ORDER BY machine_name",
    conn_1
)

conn_7.close()
conn_1.close()

# Combine and normalize
all_db_machines = pd.concat([db_7_machines, db_1_machines]).drop_duplicates()['machine_name'].tolist()
all_db_machines_lower = [m.lower() for m in all_db_machines]

print(f"\nDB total unique machines: {len(all_db_machines)}")
print(f"Sample DB machines:")
for m in all_db_machines[:15]:
    print(f"  - {m}")

# === Parse poco content to extract machine names ===
poco_df = pd.read_csv(Path("docs/poco_data_extracted.csv"))

def extract_machines_from_poco_content(content):
    """
    Extract machine names from poco content
    Example: "water day→tail:normal tail 1・3、AT tail 2・8、all→SBJ" → ["SBJ"]
    """
    if not content or pd.isna(content):
        return []

    content = str(content).strip()

    # Find machine section after "all→"
    if "全→" in content:
        machine_part = content.split("全→")[-1].strip()
        # Split by comma/period
        machines = re.split(r'[,、。]', machine_part)
        # Clean up
        machines = [m.strip() for m in machines if m.strip()]
        return machines

    return []

# Extract all machines mentioned in poco
poco_7_content = poco_df[poco_df['kamata7_content'].notna()]['kamata7_content']
poco_1_content = poco_df[poco_df['kamata1_content'].notna()]['kamata1_content']

all_poco_machines = set()
for content in poco_7_content:
    all_poco_machines.update(extract_machines_from_poco_content(content))

for content in poco_1_content:
    all_poco_machines.update(extract_machines_from_poco_content(content))

poco_machines_list = sorted(list(all_poco_machines))

print(f"\nPoco total unique machines: {len(poco_machines_list)}")
print(f"Poco machines mentioned:")
for m in poco_machines_list[:20]:
    print(f"  - {m}")

# === Match poco machines with DB ===
print(f"\n{'='*120}")
print("POCO vs DB RECONCILIATION")
print(f"{'='*120}")

reconciliation = []

for poco_machine in poco_machines_list:
    poco_lower = poco_machine.lower()

    # Exact match (case-insensitive)
    exact_matches = [m for m, ml in zip(all_db_machines, all_db_machines_lower) if ml == poco_lower]

    if exact_matches:
        db_machine = exact_matches[0]
        status = "OK"
    else:
        # Try partial match (substring)
        partial_matches = [m for m, ml in zip(all_db_machines, all_db_machines_lower)
                          if poco_lower in ml or ml in poco_lower]

        if partial_matches:
            db_machine = " | ".join(partial_matches[:2])
            status = "PARTIAL"
        else:
            db_machine = None
            status = "NOT FOUND"

    reconciliation.append({
        'poco_machine': poco_machine,
        'status': status,
        'db_match': db_machine
    })

df_reconciliation = pd.DataFrame(reconciliation)

# Display by status
print("\n### OK (Exact Match) ###")
df_ok = df_reconciliation[df_reconciliation['status'] == 'OK']
print(f"Count: {len(df_ok)}\n")
for _, row in df_ok.iterrows():
    print(f"  {row['poco_machine']:<35} [OK] → {row['db_match']}")

print("\n### PARTIAL (Substring Match - Review) ###")
df_partial = df_reconciliation[df_reconciliation['status'] == 'PARTIAL']
print(f"Count: {len(df_partial)}\n")
for _, row in df_partial.iterrows():
    print(f"  {row['poco_machine']:<35} [?]  → {row['db_match']}")

print("\n### NOT FOUND (Requires Manual Resolution) ###")
df_not_found = df_reconciliation[df_reconciliation['status'] == 'NOT FOUND']
print(f"Count: {len(df_not_found)}\n")
for _, row in df_not_found.iterrows():
    print(f"  {row['poco_machine']:<35} [X]  → ???")

# === Export reconciliation table for user ===
output_path = Path("docs/poco_machine_reconciliation.csv")
df_reconciliation.to_csv(output_path, index=False, encoding='utf-8')
print(f"\n[Output saved to: {output_path}]")

# === Summary ===
print(f"\n{'='*120}")
print("SUMMARY")
print(f"{'='*120}")
print(f"Total poco machines:          {len(poco_machines_list)}")
print(f"  - Exact match (OK):         {len(df_ok)}")
print(f"  - Partial match (review):   {len(df_partial)}")
print(f"  - Not found (manual help):  {len(df_not_found)}")

if len(df_not_found) > 0:
    print(f"\nUser action needed for {len(df_not_found)} machine(s)")
    print("→ Please edit reconciliation CSV to add correct DB machine names")

print(f"\n{'='*120}")
