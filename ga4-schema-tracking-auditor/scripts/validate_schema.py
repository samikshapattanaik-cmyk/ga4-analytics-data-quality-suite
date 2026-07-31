#!/usr/bin/env python3
"""
validate_schema.py — GA4 Schema & Tracking Auditor core engine.

Compares an OBSERVED GA4 data export (BigQuery export, GA4 Data API pull, GTM
Preview JSON, or a CSV/Excel/Google-Sheets export) against a TRACKING PLAN
(either a user-supplied spec, or the bundled default in
references/ga4-default-spec.json) and emits structured JSON findings tiered
into CRITICAL / WARNING / NOTICE.

This script never invents data. If a file can't be parsed, or a required
dependency is missing, it stops and prints a clear, human-readable error to
stderr along with a suggested fix, rather than guessing at rows that were
never actually there.

Dependencies: JSON, JSONL, CSV, and TSV (which covers every Google Sheets export,
since Sheets always downloads as CSV/TSV) are parsed with the Python standard
library only — no install required. pandas + openpyxl are only imported, and only
required, when the input is a genuine binary Excel file (.xlsx/.xls).

Usage:
    python validate_schema.py --observed export.json [--tracking-plan plan.csv] [--output findings.json]
    python validate_schema.py --observed export.csv --format tabular
    python validate_schema.py --observed export.jsonl --tracking-plan plan.json --output findings.json
    python validate_schema.py --observed export.json --output findings.json --excel-output findings.xlsx

Exit codes:
    0 = ran successfully (findings may or may not be empty)
    1 = could not run (bad input, missing dependency, bad tracking plan, etc.)
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict

# pandas + openpyxl are ONLY needed for genuine binary Excel files (.xlsx/.xls) —
# that's a zipped XML container, so there's no reasonable stdlib-only way to read it.
# CSV, TSV, JSON, and JSONL (including Google Sheets exports, which are always
# CSV/TSV under the hood) are handled with Python's standard library below, so the
# common path never requires installing anything.
try:
    import pandas as pd
except ImportError:  # pragma: no cover - exercised only when pandas truly absent
    pd = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CRITICAL = "CRITICAL"
WARNING = "WARNING"
NOTICE = "NOTICE"
_TIER_RANK = {CRITICAL: 0, WARNING: 1, NOTICE: 2}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_SPEC_PATH = os.path.join(SKILL_ROOT, "references", "ga4-default-spec.json")


# ---------------------------------------------------------------------------
# Error handling — never hallucinate, always fail loud and clear
# ---------------------------------------------------------------------------

class AuditorError(Exception):
    """Raised for any condition that should stop execution with a clear message."""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.message = message
        self.hint = hint


def fail(message, hint=None):
    raise AuditorError(message, hint)


def emit_fatal_and_exit(err: AuditorError):
    sys.stderr.write(f"ERROR: {err.message}\n")
    if err.hint:
        sys.stderr.write(f"HINT: {err.hint}\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# String / casing helpers
# ---------------------------------------------------------------------------

def normalize_key(name):
    """Case- and separator-insensitive key for matching, e.g. 'Page-Location' -> 'pagelocation'."""
    if name is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def is_snake_case(name):
    if not name or not isinstance(name, str):
        return False
    return bool(re.fullmatch(r"[a-z][a-z0-9_]*", name))


def to_snake_case(name):
    """Best-effort camelCase/PascalCase/kebab-case/space-case -> snake_case."""
    s = str(name).strip()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"(?<!^)(?<![_A-Z])(?=[A-Z])", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.lower().strip("_")


def python_type_name(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    if isinstance(value, str):
        # A numeric-looking string is exactly the "value passed as string" bug
        # we want to catch, so classify it specially rather than as plain "string".
        if re.fullmatch(r"-?\d+", value):
            return "numeric_string_int"
        if re.fullmatch(r"-?\d+\.\d+", value):
            return "numeric_string_float"
        if value.lower() in ("true", "false"):
            return "numeric_string_bool"
        return "string"
    return type(value).__name__


def types_compatible(expected_type, observed_value):
    """Return (is_match: bool, is_stringified_number: bool)."""
    if expected_type in (None, "any"):
        return True, False
    actual = python_type_name(observed_value)
    if expected_type == "string":
        return actual in ("string",), False
    if expected_type == "int":
        if actual == "int":
            return True, False
        if actual == "numeric_string_int":
            return False, True
        return False, False
    if expected_type == "float":
        if actual in ("int", "float"):
            return True, False
        if actual in ("numeric_string_int", "numeric_string_float"):
            return False, True
        return False, False
    if expected_type == "bool":
        if actual == "bool":
            return True, False
        if actual == "numeric_string_bool":
            return False, True
        return False, False
    return True, False


# ---------------------------------------------------------------------------
# Tracking plan loading
# ---------------------------------------------------------------------------

def load_default_spec():
    try:
        with open(DEFAULT_SPEC_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        fail(
            f"Could not find the bundled default GA4 spec at '{DEFAULT_SPEC_PATH}'.",
            "This file should ship inside references/ alongside this script. "
            "If it's missing, re-download the skill, or pass --tracking-plan to supply your own spec.",
        )
    except json.JSONDecodeError as e:
        fail(f"The bundled default spec at '{DEFAULT_SPEC_PATH}' is not valid JSON: {e}")
    if "events" not in raw:
        fail(
            f"The bundled default spec at '{DEFAULT_SPEC_PATH}' is missing its top-level 'events' key.",
            "This file ships with the skill and shouldn't normally be hand-edited into a broken state — "
            "if it has been, restore it from the skill source, or pass --tracking-plan to bypass it entirely.",
        )
    return raw["events"]


def _is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _coerce_from_text(value):
    """
    CSV/TSV has no native types — every cell is text. pandas' read_csv used to paper
    over this by auto-inferring numeric dtypes, so a genuinely-numeric column like
    `value` would come back as a real float rather than the string "49.99". Since we
    no longer require pandas for plain-text formats, replicate that same inference
    here: numeric-looking text becomes a real int/float/bool, everything else stays
    a string. This keeps CSV/TSV behavior consistent with Excel (where openpyxl already
    hands back typed cells) and avoids flagging every ordinary numeric CSV column as a
    false "value sent as string" type mismatch.
    """
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


def _read_delimited_rows(path, delimiter):
    """Read a CSV/TSV file into a list of dicts using only the standard library."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            if reader.fieldnames is None:
                fail(f"'{path}' appears to be empty (no header row found).")
            fieldnames = list(reader.fieldnames)
            rows = [{k: _coerce_from_text(v) for k, v in raw_row.items()} for raw_row in reader]
    except UnicodeDecodeError as e:
        fail(
            f"Could not read '{path}' as UTF-8 text: {e}",
            "This might actually be a binary Excel file saved with a .csv extension — "
            "try re-exporting it as a genuine .xlsx, or re-save it as CSV from your spreadsheet app.",
        )
    return rows, fieldnames


def _read_excel_rows(path):
    """Read a genuine .xlsx/.xls file into a list of dicts. Requires pandas + openpyxl."""
    if pd is None:
        fail(
            "This is a binary Excel file, which needs pandas + openpyxl to read (there's no "
            "standard-library way to parse the .xlsx/.xls container format).",
            "Install them in your environment (e.g. `pip install pandas openpyxl`, using a "
            "virtualenv or `--break-system-packages` if your environment requires it), "
            "or — usually simpler — re-export this file as CSV from Excel/Google Sheets and "
            "point me at that instead; CSV needs no extra dependencies at all.",
        )
    try:
        df = pd.read_excel(path)
    except Exception as e:
        fail(
            f"Could not read '{path}' as Excel: {e}",
            "Is openpyxl installed? Or is this actually a renamed CSV/TSV in disguise? "
            "Try re-exporting the file and running again.",
        )
    df.columns = [str(c).strip() for c in df.columns]
    records = df.to_dict(orient="records")
    return records, list(df.columns)


def _clean_tier(value):
    v = str(value).strip().upper() if value not in (None, "") else "WARNING"
    return v if v in (CRITICAL, WARNING, NOTICE) else WARNING


def _clean_type(value):
    v = str(value).strip().lower() if value not in (None, "") else "any"
    return v if v in ("string", "int", "float", "bool", "any") else "any"


def _clean_required(value):
    """
    Defaults to True (present-by-default) when unspecified, matching prior behavior.
    Accepts booleans directly (from JSON) or common text forms (from CSV/TSV/Excel).
    """
    if value is None or value == "":
        return True
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("false", "0", "no", "n", "optional"):
        return False
    return True


def _spec_from_long_records(records):
    """
    records: iterable of dicts with at least event_name + param_name.
    Optional: scope (event|item), tier, data_type, notes, required.
    """
    spec = OrderedDict()
    for row in records:
        event = (row.get("event_name") or row.get("event") or "").strip()
        if not event:
            continue
        param = (row.get("param_name") or row.get("parameter") or row.get("param") or "").strip()
        if not param:
            continue
        scope = str(row.get("scope") or "event").strip().lower()
        tier = _clean_tier(row.get("tier"))
        dtype = _clean_type(row.get("data_type") or row.get("type"))
        notes = str(row.get("notes") or "").strip()
        required = _clean_required(row.get("required"))

        spec.setdefault(event, {"category": "custom", "params": {}, "items": {}})
        bucket = "items" if scope.startswith("item") else "params"
        spec[event][bucket][param] = {"tier": tier, "type": dtype, "notes": notes, "required": required}
    if not spec:
        fail(
            "The tracking plan was read but produced zero usable rows.",
            "Double check it has an 'event_name' column/key and a 'param_name' column/key with values in them.",
        )
    return spec


def load_custom_tracking_plan(path):
    if not os.path.exists(path):
        fail(f"Tracking plan file not found: '{path}'.")

    ext = os.path.splitext(path)[1].lower()

    if ext == ".json":
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            fail(f"Could not parse '{path}' as JSON: {e}",
                 "Check for a trailing comma or unclosed bracket, or export the plan as CSV instead.")
        # Two shapes accepted: {"events": {...}} matching our native spec shape,
        # or a flat list of long-format records.
        if isinstance(raw, dict) and "events" in raw:
            return raw["events"]
        if isinstance(raw, list):
            return _spec_from_long_records(raw)
        fail(
            f"'{path}' is valid JSON but not in a recognized tracking-plan shape.",
            'Expected either {"events": {...}} (native spec format) or a flat list of '
            '{"event_name": ..., "param_name": ..., "scope": ..., "tier": ..., "data_type": ..., '
            '"required": ...} records.',
        )

    if ext in (".csv", ".tsv", ".xlsx", ".xls"):
        if ext == ".csv":
            records, columns = _read_delimited_rows(path, delimiter=",")
        elif ext == ".tsv":
            records, columns = _read_delimited_rows(path, delimiter="\t")
        else:
            records, columns = _read_excel_rows(path)

        columns = [str(c).strip() for c in columns]
        cols_lower = {c.lower(): c for c in columns}
        if "event_name" not in cols_lower or not any(
            k in cols_lower for k in ("param_name", "parameter", "param")
        ):
            fail(
                f"Tracking plan '{path}' is missing required column(s).",
                "Expected at least an 'event_name' column and a 'param_name' "
                "(or 'parameter'/'param') column. Optional columns: 'scope' (event|item), "
                "'tier' (CRITICAL|WARNING|NOTICE), 'data_type' (string|int|float|bool), 'notes', "
                "'required' (true|false, defaults to true). "
                f"Columns found: {columns}",
            )
        # Normalize keys to the lowercase names _spec_from_long_records expects.
        normalized = []
        for row in records:
            normalized.append({str(k).strip().lower(): v for k, v in row.items()})
        return _spec_from_long_records(normalized)

    fail(
        f"Unrecognized tracking plan file type '{ext}'.",
        "Supported formats: .json, .csv, .tsv, .xlsx, .xls. "
        "If this came from Google Sheets, use File > Download > CSV first.",
    )


# ---------------------------------------------------------------------------
# Observed data loading — format auto-detection
# ---------------------------------------------------------------------------

def detect_and_load_observed(path, format_override=None):
    if not os.path.exists(path):
        fail(f"Observed data file not found: '{path}'.")

    ext = os.path.splitext(path)[1].lower()
    fmt = format_override

    if fmt is None:
        if ext in (".json", ".jsonl", ".ndjson"):
            fmt = _sniff_json_shape(path, ext)
        elif ext in (".csv", ".tsv", ".xlsx", ".xls"):
            fmt = "tabular"
        else:
            fail(
                f"Unrecognized observed-data file type '{ext}'.",
                "Supported formats: BigQuery JSON/JSONL export (.json/.jsonl), GTM Preview JSON (.json), "
                "GA4 Data API JSON pull (.json), or a CSV/TSV/Excel/Google Sheets export (.csv/.tsv/.xlsx/.xls). "
                "Pass --format to force one explicitly if auto-detection guesses wrong.",
            )

    if fmt == "bq_json":
        return _load_bq_json(path, ext), fmt
    if fmt == "ga4_api_json":
        return _load_ga4_api_json(path), fmt
    if fmt == "gtm_preview_json":
        return _load_gtm_preview_json(path), fmt
    if fmt == "tabular":
        return _load_tabular(path, ext), fmt
    fail(f"Unknown --format override '{fmt}'. Expected one of: bq_json, ga4_api_json, gtm_preview_json, tabular.")


def _read_json_or_jsonl(path, ext):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
    except UnicodeDecodeError as e:
        fail(f"Could not read '{path}' as UTF-8 text: {e}",
             "Is this actually a binary/Excel file with a .json extension? Try re-exporting it.")
    if not text:
        fail(f"'{path}' is empty.")
    if ext in (".jsonl", ".ndjson") or (text[0] != "[" and text[0] != "{" and "\n" in text):
        rows = []
        for i, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                fail(f"Line {i} of '{path}' is not valid JSON: {e}",
                     "This looked like newline-delimited JSON (JSONL) — check that every line is one complete JSON object.")
        return rows
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        fail(f"Could not parse '{path}' as JSON: {e}",
             "If this is a newline-delimited BigQuery export, try renaming it to .jsonl and re-running.")


def _sniff_json_shape(path, ext):
    parsed = _read_json_or_jsonl(path, ext)
    sample = None
    if isinstance(parsed, list) and parsed:
        sample = parsed[0]
    elif isinstance(parsed, dict):
        if "rows" in parsed and ("dimensionHeaders" in parsed or "metricHeaders" in parsed):
            return "ga4_api_json"
        if "dataLayer" in parsed and isinstance(parsed["dataLayer"], list) and parsed["dataLayer"]:
            sample = parsed["dataLayer"][0]
        else:
            sample = parsed

    if isinstance(sample, dict):
        if "event_params" in sample or "event_name" in sample and "items" in sample:
            return "bq_json"
        if "event_params" in sample:
            return "bq_json"
        if "event" in sample and ("ecommerce" in sample or "gtm.uniqueEventId" in sample or "gtm.start" in str(sample)):
            return "gtm_preview_json"
        if "event" in sample:
            return "gtm_preview_json"
        if "event_name" in sample:
            return "bq_json"

    fail(
        f"Could not confidently auto-detect the JSON structure of '{path}'.",
        "Pass --format explicitly: bq_json (BigQuery export rows with event_params/items), "
        "gtm_preview_json (GTM Preview / dataLayer dump), or ga4_api_json (GA4 Data API pull with rows/dimensionHeaders).",
    )


# --- BigQuery-style export -------------------------------------------------

def _bq_param_value(value_struct):
    if not isinstance(value_struct, dict):
        return value_struct
    for key in ("string_value", "int_value", "float_value", "double_value"):
        if key in value_struct and value_struct[key] is not None:
            val = value_struct[key]
            if key == "int_value":
                try:
                    return int(val)
                except (TypeError, ValueError):
                    return val
            if key in ("float_value", "double_value"):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return val
            return val
    return None


def _load_bq_json(path, ext):
    rows = _read_json_or_jsonl(path, ext)
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("data") or [rows]
    if not isinstance(rows, list):
        fail(f"Expected '{path}' to contain a list of event rows for BigQuery-style export.")

    events = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        event_name = row.get("event_name") or row.get("eventName")
        if not event_name:
            continue
        params = {}
        for p in row.get("event_params") or []:
            key = p.get("key")
            if not key:
                continue
            params[key] = _bq_param_value(p.get("value"))

        items = []
        for item in row.get("items") or []:
            if isinstance(item, dict):
                items.append(dict(item))

        events.append({
            "event_name": event_name,
            "source_ref": f"row {i + 1}",
            "params": params,
            "items": items,
        })

    if not events:
        fail(
            f"'{path}' parsed as JSON but no rows contained a usable 'event_name'.",
            "Confirm this is really a GA4 BigQuery export table dump (rows with event_name/event_params/items).",
        )
    return events


# --- GTM Preview / dataLayer dump -----------------------------------------

def _flatten_gtm_object(obj, prefix=""):
    flat = {}
    items = []
    for k, v in obj.items():
        if k in ("event", "gtm.uniqueEventId", "gtm.start", "eventCallback", "eventTimeout"):
            continue
        if k == "ecommerce" and isinstance(v, dict):
            for ek, ev in v.items():
                if ek == "items" and isinstance(ev, list):
                    for item in ev:
                        if isinstance(item, dict):
                            items.append(dict(item))
                else:
                    flat[ek] = ev
            continue
        if k == "items" and isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    items.append(dict(item))
            continue
        if isinstance(v, (dict, list)):
            continue  # skip other nested structures we don't have a defined shape for
        flat[f"{prefix}{k}"] = v
    return flat, items


def _load_gtm_preview_json(path):
    parsed = _read_json_or_jsonl(path, os.path.splitext(path)[1].lower())
    if isinstance(parsed, dict) and "dataLayer" in parsed:
        pushes = parsed["dataLayer"]
    elif isinstance(parsed, list):
        pushes = parsed
    else:
        pushes = [parsed]

    events = []
    for i, push in enumerate(pushes):
        if not isinstance(push, dict):
            continue
        event_name = push.get("event")
        if not event_name:
            continue
        params, items = _flatten_gtm_object(push)
        events.append({
            "event_name": event_name,
            "source_ref": f"dataLayer push #{i + 1}",
            "params": params,
            "items": items,
        })

    if not events:
        fail(
            f"'{path}' parsed as JSON but no entries contained an 'event' key.",
            "Confirm this is a GTM Preview / dataLayer export where each push has an 'event' field.",
        )
    return events


# --- GA4 Data API JSON pull (best-effort) ----------------------------------

def _load_ga4_api_json(path):
    parsed = _read_json_or_jsonl(path, ".json")
    dim_headers = [h.get("name") for h in parsed.get("dimensionHeaders", [])]
    met_headers = [h.get("name") for h in parsed.get("metricHeaders", [])]
    rows = parsed.get("rows", [])
    if not rows:
        fail(
            f"'{path}' looks like a GA4 Data API response but has no rows.",
            "Nothing to audit — re-run the API report with a non-empty date range.",
        )

    event_name_idx = None
    for i, name in enumerate(dim_headers):
        if name and "eventname" in name.lower().replace("_", ""):
            event_name_idx = i
            break
    if event_name_idx is None:
        fail(
            f"Could not find an eventName dimension in '{path}'.",
            f"GA4 Data API pulls need an 'eventName' dimension included in the report. "
            f"Dimension headers found: {dim_headers}",
        )

    events = []
    for i, row in enumerate(rows):
        dim_values = [dv.get("value") for dv in row.get("dimensionValues", [])]
        met_values = [mv.get("value") for mv in row.get("metricValues", [])]
        event_name = dim_values[event_name_idx] if event_name_idx < len(dim_values) else None
        if not event_name:
            continue
        params = {}
        for h, v in zip(dim_headers, dim_values):
            if h and h != dim_headers[event_name_idx]:
                params[h] = v
        for h, v in zip(met_headers, met_values):
            if h:
                try:
                    params[h] = float(v)
                except (TypeError, ValueError):
                    params[h] = v
        events.append({
            "event_name": event_name,
            "source_ref": f"api row {i + 1}",
            "params": params,
            "items": [],
        })

    if not events:
        fail(f"'{path}' had rows but none resolved to a usable event name.")
    return events


# --- CSV / Excel / Google Sheets export (tabular) --------------------------

def _load_tabular(path, ext):
    """
    Load a CSV/TSV/Excel observed-data export. CSV and TSV — which covers every
    Google Sheets export, since Sheets always exports to one of those two — are read
    with the standard library and need no extra dependencies. Only genuine binary
    Excel files (.xlsx/.xls) fall through to pandas + openpyxl, since that's a zipped
    binary container with no reasonable stdlib-only reader.
    """
    if ext == ".csv":
        records, columns = _read_delimited_rows(path, delimiter=",")
    elif ext == ".tsv":
        records, columns = _read_delimited_rows(path, delimiter="\t")
    else:
        records, columns = _read_excel_rows(path)

    columns = [str(c).strip() for c in columns]
    cols_lower = {c.lower(): c for c in columns}

    event_col = next((cols_lower[c] for c in ("event_name", "eventname", "event") if c in cols_lower), None)
    if event_col is None:
        fail(
            f"Could not find an event name column in '{path}'.",
            f"Expected a column called 'event_name' (or 'eventName'/'event'). Columns found: {columns}. "
            "If this file uses a different column name, rename it and re-run, or ask me to help map columns.",
        )

    long_format_key_col = next(
        (cols_lower[c] for c in ("param_name", "parameter", "param", "param_key") if c in cols_lower), None
    )
    long_format_val_col = next((cols_lower[c] for c in ("param_value", "value") if c in cols_lower), None)

    events = []
    if long_format_key_col and long_format_val_col:
        # Long format: one row per (event occurrence, parameter). Group rows back into
        # occurrences by an explicit occurrence/event id column when present. Without
        # one, there's no way to tell apart two separate firings of the same event, so
        # rows sharing an event_name are merged into a single representative occurrence
        # for that event — accurate for a "here's one example row per parameter" style
        # export, but add an occurrence_id column if you need per-firing granularity.
        scope_col = next((cols_lower[c] for c in ("scope",) if c in cols_lower), None)
        occurrence_col = next(
            (cols_lower[c] for c in ("occurrence_id", "event_id", "row_id") if c in cols_lower), None
        )
        # An optional column to tell multiple items in the same occurrence apart. Without
        # one, all item-scoped rows for an occurrence are assumed to describe a single item
        # and get merged into one item object — add an item_index column if a real
        # occurrence has more than one item and you need them told apart.
        item_index_col = next(
            (cols_lower[c] for c in ("item_index", "item_row", "item_id_index") if c in cols_lower), None
        )
        grouped = OrderedDict()
        for row in records:
            event_name = row.get(event_col)
            if _is_blank(event_name):
                continue
            occ_key = row.get(occurrence_col) if occurrence_col else event_name
            scope = str(row.get(scope_col) or "event").strip().lower()
            param = row.get(long_format_key_col)
            val = row.get(long_format_val_col)
            if _is_blank(param):
                continue
            bucket = grouped.setdefault(
                occ_key, {"event_name": event_name, "params": {}, "items": OrderedDict()}
            )
            if scope.startswith("item"):
                item_key = row.get(item_index_col) if item_index_col else "0"
                bucket["items"].setdefault(item_key, {})[param] = val
            else:
                bucket["params"][param] = val
        for occ_key, bucket in grouped.items():
            events.append({
                "event_name": bucket["event_name"],
                "source_ref": f"row group '{occ_key}'",
                "params": bucket["params"],
                "items": list(bucket["items"].values()),
            })
    else:
        # Wide format: every other column is a parameter. A column literally named
        # 'items' containing a JSON string is treated as the items array.
        param_cols = [c for c in columns if c != event_col]
        items_col = next((c for c in param_cols if c.lower() == "items"), None)
        if items_col:
            param_cols.remove(items_col)

        for i, row in enumerate(records):
            event_name = row.get(event_col)
            if _is_blank(event_name):
                continue
            params = {}
            for c in param_cols:
                val = row.get(c)
                if _is_blank(val):
                    continue
                params[c] = val
            items = []
            raw_items = row.get(items_col) if items_col else None
            if not _is_blank(raw_items):
                try:
                    parsed_items = json.loads(raw_items)
                    if isinstance(parsed_items, list):
                        items = [it for it in parsed_items if isinstance(it, dict)]
                except (json.JSONDecodeError, TypeError):
                    pass  # leave items empty rather than guessing at malformed JSON
            events.append({
                "event_name": event_name,
                "source_ref": f"row {i + 2}",  # +2: 1-indexed plus header row
                "params": params,
                "items": items,
            })

    if not events:
        fail(f"'{path}' was read successfully but produced zero usable event rows.")
    return events


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------

def build_spec_index(spec):
    """normalized event name -> (canonical_event_name, spec_entry)"""
    index = {}
    for event_name, entry in spec.items():
        index[normalize_key(event_name)] = (event_name, entry)
    return index


def _fix_snippet_missing(event_name, scope, param_name, expected_type, is_item):
    if is_item:
        return (
            f"Add `{param_name}` to each object in the `items[]` array for `{event_name}`, e.g.:\n"
            f"  items: [{{ ..., \"{param_name}\": <{expected_type}> }}]"
        )
    return (
        f"dataLayer.push({{ event: '{event_name}', '{param_name}': <{expected_type}> }});"
    )


def _fix_snippet_casing(observed_name, canonical_name, is_item):
    where = "item object" if is_item else "dataLayer push"
    return (
        f"Rename `{observed_name}` to `{canonical_name}` in the {where}. "
        f"GA4 treats these as two different parameters today, so data is currently split across both."
    )


def _fix_snippet_type(param_name, expected_type, observed_value, is_stringified_number):
    if is_stringified_number:
        return (
            f"Send `{param_name}` as a raw number, not a string: "
            f"use {repr(_try_unquote_number(observed_value))} instead of {repr(observed_value)}."
        )
    return f"Send `{param_name}` as a {expected_type}; got {python_type_name(observed_value)} ({observed_value!r})."


def _try_unquote_number(value):
    try:
        if "." in str(value):
            return float(value)
        return int(value)
    except (TypeError, ValueError):
        return value


def diff_events(observed_events, spec):
    spec_index = build_spec_index(spec)
    # findings keyed for de-duplication across many repeated occurrences of the same issue
    findings = OrderedDict()
    total_occurrences = len(observed_events)
    events_seen = set()

    def record(key, **kwargs):
        if key not in findings:
            kwargs["occurrences_affected"] = 0
            kwargs["example_source_ref"] = kwargs.get("source_ref")
            findings[key] = kwargs
        findings[key]["occurrences_affected"] += 1

    for occurrence in observed_events:
        raw_event_name = occurrence["event_name"]
        events_seen.add(raw_event_name)
        norm = normalize_key(raw_event_name)
        match = spec_index.get(norm)

        if match is None:
            key = ("unrecognized_event", raw_event_name)
            record(
                key,
                event_name=raw_event_name,
                severity=NOTICE,
                scope="event",
                parameter=None,
                issue=f"Event '{raw_event_name}' was not found in the tracking plan.",
                expected="A matching event definition in the tracking plan.",
                observed=raw_event_name,
                suggested_fix=(
                    "If this is an intentional custom event, add it to your tracking plan so future audits "
                    "recognize it. If it's an unintended typo/variant of a known event, rename it to match."
                ),
                source_ref=occurrence.get("source_ref"),
            )
            continue

        canonical_name, spec_entry = match
        if raw_event_name != canonical_name:
            key = ("event_casing", raw_event_name, canonical_name)
            record(
                key,
                event_name=raw_event_name,
                severity=NOTICE,
                scope="event",
                parameter=None,
                issue=f"Event name '{raw_event_name}' drifts from the tracking plan's canonical '{canonical_name}'.",
                expected=canonical_name,
                observed=raw_event_name,
                suggested_fix=_fix_snippet_casing(raw_event_name, canonical_name, is_item=False),
                source_ref=occurrence.get("source_ref"),
            )

        _diff_param_scope(
            occurrence, canonical_name, spec_entry.get("params", {}), occurrence.get("params", {}),
            scope="event", record=record,
        )

        item_spec = spec_entry.get("items", {})
        if item_spec:
            if occurrence.get("items"):
                for item in occurrence["items"]:
                    _diff_param_scope(
                        occurrence, canonical_name, item_spec, item, scope="item", record=record,
                    )
            else:
                # Event has an item-scoped spec but no items array at all sent — flag once,
                # based only on the item params that are actually required. If every
                # item-scoped param in the spec is optional, there's nothing to flag.
                required_item_params = {k: v for k, v in item_spec.items() if v.get("required", True)}
                if required_item_params:
                    worst_tier = min((p["tier"] for p in required_item_params.values()), key=lambda t: _TIER_RANK[t])
                    key = ("missing_items_array", canonical_name)
                    record(
                        key,
                        event_name=canonical_name,
                        severity=worst_tier,
                        scope="item",
                        parameter=None,
                        issue=f"'{canonical_name}' has no items[] array at all, but the tracking plan expects item-scoped parameters.",
                        expected="A non-empty items[] array.",
                        observed="items[] missing or empty",
                        suggested_fix=(
                            f"Populate the `items[]` array on '{canonical_name}' with at least "
                            f"{', '.join(required_item_params.keys())}."
                        ),
                        source_ref=occurrence.get("source_ref"),
                    )

    findings_list = list(findings.values())
    findings_list.sort(key=lambda f: (_TIER_RANK[f["severity"]], f["event_name"], f.get("parameter") or ""))

    summary = {
        "total_occurrences_analyzed": total_occurrences,
        "distinct_events_seen": len(events_seen),
        "critical_count": sum(1 for f in findings_list if f["severity"] == CRITICAL),
        "warning_count": sum(1 for f in findings_list if f["severity"] == WARNING),
        "notice_count": sum(1 for f in findings_list if f["severity"] == NOTICE),
    }
    return summary, findings_list


def _diff_param_scope(occurrence, canonical_event_name, param_spec, observed_params, scope, record):
    observed_index = {normalize_key(k): (k, v) for k, v in (observed_params or {}).items()}

    for spec_param, rules in param_spec.items():
        norm_param = normalize_key(spec_param)
        found = observed_index.get(norm_param)

        if found is None:
            # required defaults to True when unset — a param with no explicit "required"
            # is treated as expected-by-default, matching prior behavior for every
            # existing spec entry. Only an explicit required: false skips the "missing"
            # finding entirely, since some params (e.g. quantity on view_item) are
            # legitimately optional and shouldn't nag on every audit that omits them.
            if not rules.get("required", True):
                continue
            key = ("missing_param", canonical_event_name, scope, spec_param)
            record(
                key,
                event_name=canonical_event_name,
                severity=rules["tier"],
                scope=scope,
                parameter=spec_param,
                issue=f"Missing {'item-scoped' if scope == 'item' else 'event-scoped'} parameter '{spec_param}'.",
                expected=f"'{spec_param}' present ({rules['type']}).",
                observed="absent",
                suggested_fix=_fix_snippet_missing(canonical_event_name, scope, spec_param, rules["type"], scope == "item"),
                source_ref=occurrence.get("source_ref"),
            )
            continue

        observed_name, observed_value = found
        if observed_name != spec_param:
            key = ("param_casing", canonical_event_name, scope, spec_param, observed_name)
            record(
                key,
                event_name=canonical_event_name,
                severity=NOTICE,
                scope=scope,
                parameter=spec_param,
                issue=f"Parameter '{observed_name}' drifts from the tracking plan's canonical '{spec_param}'.",
                expected=spec_param,
                observed=observed_name,
                suggested_fix=_fix_snippet_casing(observed_name, spec_param, is_item=(scope == "item")),
                source_ref=occurrence.get("source_ref"),
            )

        is_match, is_stringified_number = types_compatible(rules["type"], observed_value)
        if not is_match:
            key = ("type_mismatch", canonical_event_name, scope, spec_param)
            record(
                key,
                event_name=canonical_event_name,
                severity=WARNING,
                scope=scope,
                parameter=spec_param,
                issue=f"'{spec_param}' expected type {rules['type']}, got {python_type_name(observed_value)}.",
                expected=rules["type"],
                observed=f"{observed_value!r} ({python_type_name(observed_value)})",
                suggested_fix=_fix_snippet_type(spec_param, rules["type"], observed_value, is_stringified_number),
                source_ref=occurrence.get("source_ref"),
            )


# ---------------------------------------------------------------------------
# Optional self-contained Excel export
# ---------------------------------------------------------------------------

_SEVERITY_FILL_COLORS = {
    CRITICAL: "F8D7DA",  # light red
    WARNING: "FFF3CD",   # light amber
    NOTICE: "D1ECF1",    # light blue
}

_EXCEL_HEADERS = [
    "Severity", "Event", "Scope", "Parameter", "Issue",
    "Expected", "Observed", "Occurrences Affected", "Suggested Fix",
]
_EXCEL_COLUMN_WIDTHS = [10, 18, 8, 20, 42, 22, 26, 10, 55]


def write_excel_findings(findings, path):
    """
    Write findings directly to an .xlsx workbook. This is entirely optional — the
    primary contract of this script is the JSON output, and a calling Claude session
    can always build a nicer-formatted workbook itself using its own xlsx tooling.
    This exists for standalone/non-interactive use (e.g. a scheduled job in this repo's
    broader data-quality suite) where nothing downstream will convert the JSON for you.

    Only imports openpyxl when actually called, so requesting plain JSON output never
    requires installing anything beyond the standard library.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        fail(
            "openpyxl is required to write an Excel findings workbook (--excel-output) but is not installed.",
            "Install it with `pip install openpyxl` (add --break-system-packages if your environment's "
            "Python blocks unmanaged installs), or drop --excel-output and use the JSON output directly — "
            "the JSON already contains everything a workbook would.",
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "GA4 Audit Findings"
    ws.append(_EXCEL_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for finding in findings:
        ws.append([
            finding.get("severity", ""),
            finding.get("event_name", ""),
            finding.get("scope", ""),
            finding.get("parameter") or "",
            finding.get("issue", ""),
            finding.get("expected", ""),
            finding.get("observed", ""),
            finding.get("occurrences_affected", ""),
            finding.get("suggested_fix", ""),
        ])
        fill_color = _SEVERITY_FILL_COLORS.get(finding.get("severity"))
        if fill_color:
            ws.cell(row=ws.max_row, column=1).fill = PatternFill(
                start_color=fill_color, end_color=fill_color, fill_type="solid"
            )

    for i, width in enumerate(_EXCEL_COLUMN_WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    ws.freeze_panes = "A2"

    try:
        wb.save(path)
    except Exception as e:
        fail(f"Could not write the Excel workbook to '{path}': {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Diff an observed GA4 data export against a tracking plan and emit tiered findings as JSON."
    )
    parser.add_argument("--observed", required=True, help="Path to the observed data export.")
    parser.add_argument(
        "--tracking-plan",
        required=False,
        default=None,
        help="Path to a custom tracking plan (.json/.csv/.tsv/.xlsx/.xls). Omit to use the bundled default spec.",
    )
    parser.add_argument(
        "--output",
        required=False,
        default=None,
        help="Path to write JSON findings to. Omit to print to stdout.",
    )
    parser.add_argument(
        "--format",
        required=False,
        default=None,
        choices=["bq_json", "ga4_api_json", "gtm_preview_json", "tabular"],
        help="Force the observed-data format instead of auto-detecting it.",
    )
    parser.add_argument(
        "--excel-output",
        required=False,
        default=None,
        help="Optional path to also write findings as an .xlsx workbook directly (requires openpyxl). "
             "Entirely optional — the JSON output already contains everything needed to build one elsewhere.",
    )
    args = parser.parse_args()

    try:
        observed_events, detected_format = detect_and_load_observed(args.observed, args.format)

        if args.tracking_plan:
            spec = load_custom_tracking_plan(args.tracking_plan)
            plan_source = f"custom:{args.tracking_plan}"
        else:
            spec = load_default_spec()
            plan_source = "bundled_default"

        summary, findings = diff_events(observed_events, spec)
        summary["observed_data_format_detected"] = detected_format
        summary["tracking_plan_source"] = plan_source

        result = {"summary": summary, "findings": findings}
        output_text = json.dumps(result, indent=2, default=str)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_text)
            print(f"Wrote {len(findings)} findings to {args.output}", file=sys.stderr)
        else:
            print(output_text)

        if args.excel_output:
            write_excel_findings(findings, args.excel_output)
            print(f"Wrote {len(findings)} findings to {args.excel_output}", file=sys.stderr)

    except AuditorError as e:
        emit_fatal_and_exit(e)
    except Exception as e:  # last-resort guard against ever hallucinating a "clean" result
        sys.stderr.write(f"UNEXPECTED ERROR: {e}\n")
        sys.stderr.write(
            "HINT: This wasn't one of the anticipated failure modes — re-check the input file by hand "
            "before trusting any partial output above.\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
