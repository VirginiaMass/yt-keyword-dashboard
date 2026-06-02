"""
rename_categories.py
--------------------
One-time script to rename category values in keyword_registry.csv.
Run from anywhere in the project:
    python tools/rename_categories.py
"""

import csv
import shutil
import os
from datetime import datetime

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(SCRIPT_DIR, '..', 'config', 'keyword_registry.csv')

RENAMES = {
    'Fiction Genres':      'Fiction',
    'Trope Intelligence':  'Trope',
    'Author Intelligence': 'Author',
}

# Backup
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_path = REGISTRY_PATH.replace('.csv', f'_backup_{ts}.csv')
shutil.copy2(REGISTRY_PATH, backup_path)
print(f"Backup written: {backup_path}")

# Read
with open(REGISTRY_PATH, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    fieldnames = list(reader.fieldnames)

# Apply renames
counts = {k: 0 for k in RENAMES}
for row in rows:
    old = row.get('category', '')
    if old in RENAMES:
        row['category'] = RENAMES[old]
        counts[old] += 1

# Write
with open(REGISTRY_PATH, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

# Report
print(f"\nRenames applied:")
for old, new in RENAMES.items():
    print(f"  '{old}' → '{new}'  ({counts[old]} rows affected)")

# Verify
with open(REGISTRY_PATH, newline='', encoding='utf-8') as f:
    rows_check = list(csv.DictReader(f))
remaining = [r['category'] for r in rows_check if r['category'] in RENAMES]
print(f"\nVerification: old names still present: {len(remaining)} (should be 0)")
print(f"Done. {len(rows_check)} rows in registry.")
