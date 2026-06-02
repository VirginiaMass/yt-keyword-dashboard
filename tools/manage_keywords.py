"""
manage_keywords.py
------------------
Utility script for managing keywords across keyword_registry.csv and keywords.csv.
Must be run BEFORE any BigQuery data exists if using --after (renumber mode).

Commands
--------
add
    Add a new keyword to both CSVs.
    Without --after : appends as next available KW ID (safe after data exists)
    With    --after : inserts after a specific KW ID, then renumbers everything
                      !! DO NOT USE --after once search_runs data exists in BigQuery !!

deactivate
    Bulk set active=FALSE in keyword_registry.csv by matching any registry field.
    Example: --where keyword_type=author

Usage examples
--------------
# Append new keyword (safe anytime):
python tools/manage_keywords.py add \\
    --keyword "cozy mystery books" \\
    --search-string "cozy mystery books" \\
    --type genre \\
    --category "Fiction Genres" \\
    --subcategory "Mystery & Thriller" \\
    --priority secondary \\
    --batch batch_2

# Insert after KW0043 and renumber (before BigQuery data exists only):
python tools/manage_keywords.py add \\
    --after KW0043 \\
    --keyword "cozy mystery books" \\
    --search-string "cozy mystery books" \\
    --type genre \\
    --category "Fiction Genres" \\
    --subcategory "Mystery & Thriller" \\
    --priority secondary \\
    --batch batch_2

# Deactivate all author keywords:
python tools/manage_keywords.py deactivate --where keyword_type=author

# Deactivate a single keyword by ID:
python tools/manage_keywords.py deactivate --where keyword_id=KW0164
"""

import csv
import argparse
import os
import sys
import shutil
from datetime import datetime

# ── Path config ──────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR  = os.path.join(SCRIPT_DIR, '..', 'config')

REGISTRY_PATH = os.path.join(CONFIG_DIR, 'keyword_registry.csv')
KEYWORDS_PATH = os.path.join(CONFIG_DIR, 'keywords.csv')

# ── Helpers ───────────────────────────────────────────────────────────────────

def backup(path: str) -> str:
    """Write a timestamped backup of a file before modifying it."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = path.replace('.csv', f'_backup_{ts}.csv')
    shutil.copy2(path, backup_path)
    return backup_path


def read_csv(path: str) -> tuple[list[dict], list[str]]:
    """Return (rows, fieldnames) from a CSV file."""
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    return rows, fieldnames


def write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    """Write rows to a CSV file."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def next_kw_id(rows: list[dict]) -> str:
    """Return the next available KW ID based on the highest existing ID."""
    ids = []
    for row in rows:
        kid = row.get('keyword_id', '')
        if kid.startswith('KW') and kid[2:].isdigit():
            ids.append(int(kid[2:]))
    next_num = max(ids) + 1 if ids else 1
    return f"KW{next_num:04d}"


def renumber(rows: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """
    Renumber all keyword_ids sequentially (KW0001, KW0002, ...).
    Returns (renumbered_rows, id_map {old_id: new_id}).
    """
    id_map = {}
    for i, row in enumerate(rows, start=1):
        old_id = row['keyword_id']
        new_id = f"KW{i:04d}"
        id_map[old_id] = new_id
        row['keyword_id'] = new_id
    return rows, id_map


def apply_id_map(rows: list[dict], id_map: dict[str, str]) -> list[dict]:
    """Apply an id_map to keyword_id column of a second file."""
    for row in rows:
        old_id = row['keyword_id']
        if old_id in id_map:
            row['keyword_id'] = id_map[old_id]
        else:
            print(f"  WARNING: keyword_id {old_id} in keywords.csv has no match in registry after renumber.")
    return rows


# ── Command: add ──────────────────────────────────────────────────────────────

def cmd_add(args: argparse.Namespace) -> None:
    # Validate required fields
    required = ['keyword', 'type', 'category', 'subcategory', 'priority', 'batch']
    missing = [f for f in required if not getattr(args, f.replace('-', '_'), None)]
    if missing:
        print(f"ERROR: Missing required fields: {', '.join(missing)}")
        sys.exit(1)

    # search_string defaults to keyword if not provided
    search_string = args.search_string if args.search_string else args.keyword

    # Read both files
    reg_rows, reg_fields   = read_csv(REGISTRY_PATH)
    kw_rows,  kw_fields    = read_csv(KEYWORDS_PATH)

    # Check for duplicate keyword label
    existing_labels = [r['keyword'].lower() for r in reg_rows]
    if args.keyword.lower() in existing_labels:
        print(f"WARNING: '{args.keyword}' already exists in keyword_registry.csv.")
        confirm = input("Add anyway? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Aborted.")
            sys.exit(0)

    if args.after:
        # ── Insert mode (renumber) ────────────────────────────────────────────
        after_id = args.after.upper()
        reg_ids = [r['keyword_id'] for r in reg_rows]

        if after_id not in reg_ids:
            print(f"ERROR: --after ID '{after_id}' not found in keyword_registry.csv.")
            sys.exit(1)

        print(f"\n!! INSERT + RENUMBER MODE !!")
        print(f"   Inserting after {after_id}.")
        print(f"   This will renumber ALL keyword_ids in both CSVs.")
        print(f"   Only safe before BigQuery data exists.\n")
        confirm = input("Confirm renumber? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Aborted.")
            sys.exit(0)

        # Build new registry row with a placeholder ID
        new_reg_row = {
            'keyword_id':  '__NEW__',
            'keyword':     args.keyword,
            'keyword_type': args.type,
            'category':    args.category,
            'subcategory': args.subcategory,
            'priority':    args.priority,
            'active':      'TRUE',
            'notes':       args.notes if args.notes else '',
        }

        # Insert into registry after --after position
        insert_pos = reg_ids.index(after_id) + 1
        reg_rows.insert(insert_pos, new_reg_row)

        # Renumber registry and get id_map
        reg_rows, id_map = renumber(reg_rows)
        new_id = reg_rows[insert_pos]['keyword_id']

        # Apply id_map to keywords.csv (shifts all existing IDs)
        kw_rows = apply_id_map(kw_rows, id_map)

        # Insert new keywords.csv row at the same ordinal position as the registry
        new_kw_row = {
            'keyword_id':    new_id,
            'search_string': search_string,
            'language':      args.language,
            'region':        args.region,
            'max_results':   args.max_results,
            'search_type':   'video',
            'order':         'date',
            'frequency':     args.frequency,
            'batch':         args.batch,
        }
        kw_rows.insert(insert_pos, new_kw_row)

        print(f"\n  Renumbered {len(reg_rows)} keywords.")
        print(f"  New keyword inserted as {new_id} after {after_id}.")

    else:
        # ── Append mode (safe anytime) ────────────────────────────────────────
        new_id = next_kw_id(reg_rows)

        new_reg_row = {
            'keyword_id':   new_id,
            'keyword':      args.keyword,
            'keyword_type': args.type,
            'category':     args.category,
            'subcategory':  args.subcategory,
            'priority':     args.priority,
            'active':       'TRUE',
            'notes':        args.notes if args.notes else '',
        }

        new_kw_row = {
            'keyword_id':   new_id,
            'search_string': search_string,
            'language':     args.language,
            'region':       args.region,
            'max_results':  args.max_results,
            'search_type':  'video',
            'order':        'date',
            'frequency':    args.frequency,
            'batch':        args.batch,
        }

        reg_rows.append(new_reg_row)
        kw_rows.append(new_kw_row)
        print(f"\n  Appended '{args.keyword}' as {new_id}.")

    # Back up and write both files
    reg_backup = backup(REGISTRY_PATH)
    kw_backup  = backup(KEYWORDS_PATH)
    print(f"\n  Backups written:")
    print(f"    {reg_backup}")
    print(f"    {kw_backup}")

    write_csv(REGISTRY_PATH, reg_rows, reg_fields)
    write_csv(KEYWORDS_PATH, kw_rows, kw_fields)
    print(f"\n  Done. Both files updated.")
    print(f"  keyword_registry.csv : {len(reg_rows)} rows")
    print(f"  keywords.csv         : {len(kw_rows)} rows")


# ── Command: deactivate ───────────────────────────────────────────────────────

def cmd_deactivate(args: argparse.Namespace) -> None:
    if not args.where:
        print("ERROR: --where is required. Example: --where keyword_type=author")
        sys.exit(1)

    if '=' not in args.where:
        print("ERROR: --where must be in format field=value. Example: --where keyword_type=author")
        sys.exit(1)

    field, value = args.where.split('=', 1)
    field = field.strip()
    value = value.strip()

    reg_rows, reg_fields = read_csv(REGISTRY_PATH)

    # Find matches
    matches = [r for r in reg_rows if r.get(field, '').lower() == value.lower()]

    if not matches:
        print(f"No rows found where {field} = '{value}'.")
        sys.exit(0)

    print(f"\n  Found {len(matches)} keyword(s) where {field} = '{value}':")
    for r in matches:
        print(f"    {r['keyword_id']}  {r['keyword']:<45}  active={r['active']}")

    confirm = input(f"\n  Set all {len(matches)} to active=FALSE? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("Aborted.")
        sys.exit(0)

    # Apply
    already_inactive = 0
    changed = 0
    for row in reg_rows:
        if row.get(field, '').lower() == value.lower():
            if row['active'].upper() == 'FALSE':
                already_inactive += 1
            else:
                row['active'] = 'FALSE'
                changed += 1

    reg_backup = backup(REGISTRY_PATH)
    print(f"\n  Backup written: {reg_backup}")

    write_csv(REGISTRY_PATH, reg_rows, reg_fields)
    print(f"\n  Done.")
    print(f"    Changed to inactive : {changed}")
    print(f"    Already inactive    : {already_inactive}")
    print(f"    keyword_registry.csv updated.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Manage keywords across keyword_registry.csv and keywords.csv.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest='command')

    # ── add ──
    add_parser = subparsers.add_parser('add', help='Add a new keyword to both CSVs.')
    add_parser.add_argument('--after',         help='Insert after this KW ID and renumber. Omit to append safely.')
    add_parser.add_argument('--keyword',       required=True, help='Human-readable keyword label (goes in registry)')
    add_parser.add_argument('--search-string', help='Search string passed to YouTube API (defaults to --keyword)')
    add_parser.add_argument('--type',          required=True, help='keyword_type: genre, trope, mood, etc.')
    add_parser.add_argument('--category',      required=True, help='Top-level category')
    add_parser.add_argument('--subcategory',   required=True, help='Mid-level subcategory')
    add_parser.add_argument('--priority',      required=True, choices=['core','secondary','exploratory'])
    add_parser.add_argument('--batch',         required=True, choices=['batch_1','batch_2','batch_3','batch_4'])
    add_parser.add_argument('--language',      default='en')
    add_parser.add_argument('--region',        default='US')
    add_parser.add_argument('--max-results',   default='50')
    add_parser.add_argument('--frequency',     default='daily', choices=['daily','weekly'])
    add_parser.add_argument('--notes',         default='', help='Optional notes for registry')

    # ── deactivate ──
    deact_parser = subparsers.add_parser('deactivate', help='Bulk set active=FALSE by field match.')
    deact_parser.add_argument('--where', required=True,
                              help='field=value filter. Examples: keyword_type=author  |  keyword_id=KW0164')

    args = parser.parse_args()

    if args.command == 'add':
        cmd_add(args)
    elif args.command == 'deactivate':
        cmd_deactivate(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
