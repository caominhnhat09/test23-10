"""Verify the exported CSV against config/dataset_config.json and record provenance.

What it does (standard library only, runs fully offline):
  * checks the CSV exists and has the required columns,
  * counts rows, duplicate unique keys, malformed/missing timestamps,
    rows outside the configured date window or borough,
  * counts open / closed / missing-status records,
  * computes the file's SHA-256 so everyone can prove they use the same file,
  * writes provenance/dataset_manifest.json (facts measured from the real file).

Nothing is invented: every number in the manifest is measured from the CSV.

Usage:
    python scripts/verify_dataset.py
    python scripts/verify_dataset.py --csv path/to/other.csv

Exit code 0 = dataset usable, 1 = critical problem (missing file/columns/rows).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "dataset_config.json"
MANIFEST_PATH = ROOT / "provenance" / "dataset_manifest.json"
DATA_SOURCE_PATH = ROOT / "DATA_SOURCE.md"
PLACEHOLDER = "<<FILL>>"

# Portal headers vary (backend name vs. display label), so map aliases.
COLUMN_ALIASES = {
    "unique_key": {"unique_key"},
    "created_date": {"created_date"},
    "closed_date": {"closed_date"},
    "agency": {"agency"},
    "agency_name": {"agency_name"},
    "complaint_type": {"complaint_type", "problem"},
    "descriptor": {"descriptor", "problem_detail"},
    "status": {"status"},
    "borough": {"borough"},
    "community_board": {"community_board"},
    "city": {"city"},
}

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %I:%M:%S %p",
)


def normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def map_columns(header: list[str]) -> dict[str, int]:
    """Return {canonical_name: column_index} for every recognised column."""
    mapping: dict[str, int] = {}
    for index, raw in enumerate(header):
        norm = normalize_header(raw)
        for canonical, aliases in COLUMN_ALIASES.items():
            if norm in aliases and canonical not in mapping:
                mapping[canonical] = index
    return mapping


def parse_timestamp(text: str) -> datetime | None:
    """Return a datetime, None if blank, or raise ValueError if malformed."""
    text = text.strip()
    if not text:
        return None
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp: {text!r}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get(row: list[str], mapping: dict[str, int], name: str) -> str:
    index = mapping.get(name)
    if index is None or index >= len(row):
        return ""
    return row[index]


def analyse(csv_path: Path, config: dict) -> dict:
    filters = config["filters"]
    window_start = datetime.fromisoformat(filters["created_date_start_inclusive"])
    window_end = datetime.fromisoformat(filters["created_date_end_exclusive"])
    expected_borough = (filters.get("borough") or "").strip().upper()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        mapping = map_columns(header)
        missing = [c for c in config["required_columns"] if c not in mapping]

        stats = {
            "rows": 0,
            "duplicate_unique_keys": 0,
            "blank_unique_keys": 0,
            "malformed_created_date": 0,
            "malformed_closed_date": 0,
            "missing_created_date": 0,
            "missing_closed_date": 0,
            "closed_before_created": 0,
            "created_outside_window": 0,
            "borough_mismatch": 0,
        }
        status_counts: Counter[str] = Counter()
        borough_counts: Counter[str] = Counter()
        seen_keys: set[str] = set()
        min_created = max_created = None

        if missing:
            return {"header": header, "missing_columns": missing, "stats": stats}

        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            stats["rows"] += 1

            key = get(row, mapping, "unique_key").strip()
            if not key:
                stats["blank_unique_keys"] += 1
            elif key in seen_keys:
                stats["duplicate_unique_keys"] += 1
            else:
                seen_keys.add(key)

            created = closed = None
            try:
                created = parse_timestamp(get(row, mapping, "created_date"))
                if created is None:
                    stats["missing_created_date"] += 1
            except ValueError:
                stats["malformed_created_date"] += 1
            try:
                closed = parse_timestamp(get(row, mapping, "closed_date"))
                if closed is None:
                    stats["missing_closed_date"] += 1
            except ValueError:
                stats["malformed_closed_date"] += 1

            if created is not None:
                min_created = created if min_created is None else min(min_created, created)
                max_created = created if max_created is None else max(max_created, created)
                if not (window_start <= created < window_end):
                    stats["created_outside_window"] += 1
                if closed is not None and closed < created:
                    stats["closed_before_created"] += 1

            status = get(row, mapping, "status").strip()
            status_counts[status or "(missing)"] += 1

            borough = get(row, mapping, "borough").strip().upper()
            borough_counts[borough or "(missing)"] += 1
            if expected_borough and borough != expected_borough:
                stats["borough_mismatch"] += 1

    return {
        "header": header,
        "missing_columns": [],
        "stats": stats,
        "status_counts": dict(status_counts.most_common()),
        "borough_counts": dict(borough_counts.most_common()),
        "created_min": min_created.isoformat() if min_created else None,
        "created_max": max_created.isoformat() if max_created else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csv", type=Path, help="CSV to check (default: csv_path from config)")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    csv_path = args.csv or (ROOT / config["csv_path"])

    if not csv_path.is_file():
        print(f"[FAIL] CSV not found: {csv_path}")
        print("       Export it first (see docs/PORTAL_FILTER_STEPS.md).")
        return 1

    result = analyse(csv_path, config)
    if result["missing_columns"]:
        print(f"[FAIL] Missing required columns: {result['missing_columns']}")
        print(f"       Header found: {result['header']}")
        return 1

    stats = result["stats"]
    if stats["rows"] == 0:
        print("[FAIL] The CSV has a header but no data rows.")
        return 1

    manifest = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "csv_file": csv_path.name,
        "csv_size_bytes": csv_path.stat().st_size,
        "csv_sha256": sha256_of(csv_path),
        "dataset_id": config["dataset_id"],
        "filters": config["filters"],
        "columns_in_file": result["header"],
        "stats": stats,
        "status_counts": result["status_counts"],
        "borough_counts": result["borough_counts"],
        "created_min_in_file": result["created_min"],
        "created_max_in_file": result["created_max"],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"File:            {csv_path.name}")
    print(f"SHA-256:         {manifest['csv_sha256']}")
    print(f"Rows:            {stats['rows']}")
    print(f"Created range:   {result['created_min']}  ->  {result['created_max']}")
    print(f"Status counts:   {result['status_counts']}")
    print(f"Borough counts:  {result['borough_counts']}")
    print("Quality counters:")
    for name, value in stats.items():
        if name != "rows":
            flag = "  <-- review" if value else ""
            print(f"  {name:<26}{value}{flag}")

    if stats["created_outside_window"] or stats["borough_mismatch"]:
        print("\n[WARN] Rows fall outside the documented filters. Re-export, or document why.")

    if DATA_SOURCE_PATH.is_file() and PLACEHOLDER in DATA_SOURCE_PATH.read_text(encoding="utf-8"):
        print(f"\n[WARN] DATA_SOURCE.md still contains {PLACEHOLDER} placeholders. "
              "Fill them in with the values above (undocumented data is a major defect).")

    print(f"\nManifest written to {MANIFEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
