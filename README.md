# NYC 311 City Service Request Analytics: Portal / Data Setup

This folder covers the **Portal/data setup** part of project 6. It delivers the documented,
reproducible dataset and the environment that the other parts (parser/indexing,
analytics/plots, validation/documentation) build on.

## Contents

| Path | Purpose |
|---|---|
| `config/dataset_config.json` | Single source of truth: dataset ID, filters, CSV path, required columns |
| `DATA_SOURCE.md` | Official source, exact filters, export facts, limitations (fill in `<<FILL>>`) |
| `docs/PORTAL_FILTER_STEPS.md` | Step-by-step export instructions and checklist |
| `scripts/check_environment.py` | Checks Python 3.11+, NumPy, Matplotlib |
| `scripts/build_export_url.py` | Prints the exact SoQL filter and export URL from the config |
| `scripts/verify_dataset.py` | Validates the CSV, counts quality issues, writes the provenance manifest |
| `provenance/` | Screenshot / saved filter description and `dataset_manifest.json` |
| `data/raw/` | The exported CSV (not included) |
| `requirements.txt` | Python dependencies |

## Workflow

```
pip install -r requirements.txt
python scripts/check_environment.py
python scripts/build_export_url.py        # or follow docs/PORTAL_FILTER_STEPS.md
# download the CSV into data/raw/ and add the screenshot / filter description to provenance/
python scripts/verify_dataset.py
# copy the measured values into DATA_SOURCE.md
```

## Hand-off to the other team members

- Parser/indexing: read `config/dataset_config.json` for the CSV path and column names.
  Portal headers may use either backend names (`complaint_type`) or labels ("Problem");
  `verify_dataset.py` shows how to map both.
- Analytics/plots: use only the frozen CSV; never re-download during analysis (offline requirement).
- Validation/documentation: reuse the counters in `dataset_manifest.json` (rows, duplicates,
  malformed timestamps, open/closed/missing status) as cross-check values, and cite `DATA_SOURCE.md`.

## How this part maps to the grading rubric

| Rubric item | Evidence in this folder |
|---|---|
| Environment/data/reproducibility (10) | Config file, documented filters, SHA-256 hash, `DATA_SOURCE.md`, provenance screenshot |
| Code quality/documentation (10) | Small readable scripts, explicit configuration, this README |
| Analysis/outputs (10) | Manifest values let later outputs be traced back to the input data |
| Testing/robustness (15) | Verification script handles missing columns, blank/malformed timestamps, duplicates |

## Rules the team must follow

- Never invent, edit by hand, or silently replace data: undocumented data is a major defect.
- Any change to the slice means: update the config, re-export, re-verify, update `DATA_SOURCE.md`.
