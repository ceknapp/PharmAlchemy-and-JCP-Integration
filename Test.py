import os
import re
import sqlite3
import pandas as pd
import sys

# ── Configuration ──
# Determine script directory; fallback to cwd if __file__ is unavailable.
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()

DDL_FILE = os.path.join(SCRIPT_DIR, "MediatedSchema.sql")
if not os.path.isfile(DDL_FILE):
    sys.exit(f"Error: '{DDL_FILE}' not found. Place MediatedSchema.sql in the script folder.")

# 1) Create in-memory SQLite database
conn = sqlite3.connect(":memory:")
cursor = conn.cursor()

# 2) Load & preview base tables from sample CSVs
print("=== Base Table Samples ===")
for fname in sorted(os.listdir(SCRIPT_DIR)):
    if fname.startswith("sample_") and fname.lower().endswith(".csv"):
        table = fname[len("sample_"):-4]  # 'sample_P2T.csv' -> 'P2T'
        df = pd.read_csv(os.path.join(SCRIPT_DIR, fname))
        print(f"\n-- {table} (first 3 rows) --")
        print(df.head(3))
        # Create table schema
        cols_ddl = ", ".join(f'"{c}" TEXT' for c in df.columns)
        cursor.execute(f'CREATE TABLE "{table}" ({cols_ddl});')
        # Bulk insert data
        placeholders = ", ".join("?" for _ in df.columns)
        cursor.executemany(
            f'INSERT INTO "{table}" VALUES ({placeholders});',
            df.itertuples(index=False, name=None)
        )

# 3) Read & sanitize the DDL script
with open(DDL_FILE, "r") as f:
    raw_ddl = f.read()

clean_ddl = re.sub(r'CREATE\s+OR\s+REPLACE\s+VIEW', "CREATE VIEW", raw_ddl, flags=re.IGNORECASE)
clean_ddl = re.sub(r'@\w+', "", clean_ddl)                             # strip @jcp_link etc.
clean_ddl = re.sub(r'\bJCP\.', "", clean_ddl, flags=re.IGNORECASE)     # remove schema qualifiers
clean_ddl = re.sub(r'\bPHARMALCHEMY\.', "", clean_ddl, flags=re.IGNORECASE)

# 4) Filter and execute only the G_ views
parts   = re.split(r';\s*', clean_ddl)
g_views = [p.strip() + ";" for p in parts if re.match(r'CREATE VIEW\s+G_', p, flags=re.IGNORECASE)]
cursor.executescript("\n".join(g_views))
print("\n✅ G_ views created in SQLite")

# 5) Preview mediated views
print("\n=== Mediated View Samples ===")
for view in ("G_JCP2PHARMA", "G_P2T", "G_PERTURBAGEN", "G_WELL"):
    try:
        dfv = pd.read_sql_query(f'SELECT * FROM "{view}" LIMIT 3;', conn)
        print(f"\n-- {view} (first 3 rows) --")
        print(dfv)
    except Exception as e:
        print(f"ERROR selecting from {view}: {e}")

# 6) Compute and display integration metrics
print("\n=== Integration Metrics ===")

def count_rows(table):
    return cursor.execute(f'SELECT COUNT(*) FROM "{table}";').fetchone()[0]

# Metric: G_JCP2PHARMA coverage & unmatched
base_ct = count_rows("PERTURBAGEN")
view_ct = count_rows("G_JCP2PHARMA")
coverage = view_ct / base_ct if base_ct else 0
missing  = cursor.execute('''
    SELECT COUNT(*) FROM "PERTURBAGEN" p
    LEFT JOIN "R" r ON p."metadata_smiles" = r."SMILES"
    WHERE r."SMILES" IS NULL;
''').fetchone()[0]
print(f"G_JCP2PHARMA coverage: {view_ct}/{base_ct} ({coverage:.1%})")
print(f"G_JCP2PHARMA unmatched: {missing}/{base_ct} ({missing/base_ct:.1%})\n")

# Metric: G_P2T coverage
base_ct = count_rows("P2T")
view_ct = count_rows("G_P2T")
coverage = view_ct / base_ct if base_ct else 0
print(f"G_P2T coverage: {view_ct}/{base_ct} ({coverage:.1%})\n")

# Metric: G_WELL coverage
base_ct = count_rows("WELL")
view_ct = count_rows("G_WELL")
coverage = view_ct / base_ct if base_ct else 0
print(f"G_WELL coverage: {view_ct}/{base_ct} ({coverage:.1%})\n")

# 7) Close
conn.close()
