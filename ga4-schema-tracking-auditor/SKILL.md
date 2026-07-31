---
name: ga4-schema-tracking-auditor
description: Audits GA4 event tracking for drift against a tracking plan—catches missing required parameters, data type mismatches (e.g. "49.99" instead of 49.99), and casing drift (e.g. pageLocation vs page_location) across both standard web analytics events (page_view, generate_lead, sign_up, search, login, file_download) and ecommerce events (view_item, add_to_cart, begin_checkout, purchase), including item-scoped parameters inside the items[] array. Use this whenever the user wants to QA, validate, or audit their GA4 tracking implementation, check a GA4 BigQuery export, GTM Preview dump, Data API pull, or tracking plan spreadsheet for tagging errors, investigate why GA4 reports look fragmented or incomplete, or reconcile an analytics tracking plan against production data.
---

# GA4 Schema & Tracking Auditor

This skill compares observed GA4 events against a reference tracking plan, reporting gaps according to three severity tiers:

- 🔴 **CRITICAL:** A load-bearing event/parameter is missing (breaks core GA4 processing or revenue reporting), or a load-bearing parameter's item-array is missing entirely.
- 🟡 **WARNING:** A parameter is present but wrong — a data type mismatch (e.g. `"49.99"` instead of `49.99`). WARNING is reserved for something actually being wrong, never for a parameter simply being absent.
- 🔵 **NOTICE:** Either a recommended-but-not-load-bearing parameter is absent, naming/casing drift is fragmenting reports (e.g. `pageLocation` vs `page_location`), or an observed parameter is a known common misnomer for a real one the plan expects (e.g. `item_code` when the plan expects `item_id`). Absence of anything non-critical is deliberately kept at this lower tier so the report stays focused on real problems instead of nagging about every optional field a legitimate implementation chose to skip.

All parsing, unnesting, and diffing logic is executed deterministically via `scripts/validate_schema.py`, which emits two views of the same findings:
- **`findings`** — granular, one entry per (event, scope, parameter, issue), for anyone who wants full detail.
- **`event_reports`** — aggregated one row per distinct (event, issue-pattern) combination, each bundling every issue for that pattern together with a single ready-to-paste `dataLayer.push` fix block. **This is the view to build the in-chat report and Excel workbook from.**

---

## Workflow Execution Steps

### Step 1: Confirm Setup & Input Sources

Before executing the script, confirm the input sources with the user:

1. **Tracking Plan:** "Do you have your own tracking plan (Sheets/CSV/Excel/JSON), or should I use the bundled GA4 default spec? No `tier`/`required` columns needed — I'll infer those. Add them yourself if you want tighter control over what counts as CRITICAL vs optional."
2. **Observed Data:** "Is your observed export attached/pasted directly, or are we connecting to a database/warehouse (e.g., BigQuery)?"
   - *Note for BigQuery/Warehouses:* Ask the user to confirm the exact project/dataset/table name and column mappings for `event_name`, `event_params`, and `items` before querying.

*If both inputs are already provided in the prompt, confirm understanding in one line and proceed directly to Step 2.*

### Step 2: Input Handling & File Normalization

- For uploaded files, use the provided file paths directly.
- For copy-pasted data (Google Sheets TSV, raw JSON), write the raw text directly to a working file (e.g., `/tmp/observed.csv` or `/tmp/plan.json`) before running the script.
- **Error Safety Net:** Never invent or hallucinate synthetic data rows if a file or connection fails to parse. If reading fails or a dependency is missing, stop and surface the script's error message and hint to the user rather than working around it silently.

### Step 3: Run the Schema Validator Script

Execute the bundled Python validation script using `argparse`:

```bash
python3 scripts/validate_schema.py --observed <PATH_TO_OBSERVED_DATA> [--tracking-plan <PATH_TO_PLAN>] --output /tmp/findings.json
```

- Omit `--tracking-plan` to fall back to the bundled default spec (`references/ga4-default-spec.json`).
- The script auto-detects the observed data format across **five** shapes: BigQuery-style export (rows with `event_params`/`items` array structs), GTM Preview/dataLayer JSON dump (`{event: ..., ecommerce: {...}}`), **flat gtag.js-style event capture** (`{event_name: ..., ...flat params..., items: [...]}` with no wrapper — the natural output of tools that intercept and log raw `gtag('event', ...)` calls), GA4 Data API JSON pull (rows + dimensionHeaders), or tabular CSV/TSV/Excel. If detection isn't confident, it exits with an error instead of guessing—pass `--format bq_json`, `--format gtm_preview_json`, `--format flat_json`, `--format ga4_api_json`, or `--format tabular` to force it.
- **Dependencies:** JSON, JSONL, CSV, and TSV need nothing beyond the Python standard library—this covers every Google Sheets export, since Sheets always downloads as CSV/TSV. `pandas` + `openpyxl` are only imported, and only needed, when the file is a genuine binary Excel workbook (`.xlsx`/`.xls`). If the script reports them missing for an Excel input, the simplest fix is usually to ask the user to re-export the same file as CSV instead (Google Sheets/Excel: File > Download > CSV)—no dependency involved. If they specifically need the Excel file read as-is, install the two packages using whatever approach fits the environment (a virtualenv, `pip install pandas openpyxl`, or that same command with `--break-system-packages` if the environment's Python blocks unmanaged installs) and retry once.
- **Custom tracking plan columns:** at minimum an `event_name` column and a `param_name` column (aliases `parameter`/`param`/`parameter_name` are also recognized), or an equivalent flat JSON list of records. Optional columns: `scope`/`parameter_scope` (`event`|`item`, defaults to `event`), `data_type`/`parameter_type` (`string`|`int`|`float`|`bool`, defaults to `any`), `notes`/`description`, `tier` (`CRITICAL`|`WARNING`|`NOTICE`), `required` (`true`|`false`).
- **Tier/required are almost never mandatory columns** — most real-world tracking plans (a marketing-authored Sheet, for instance) don't have them at all. When either is left unset for a parameter, the script resolves it through a 3-layer fallback, in priority order: **(1)** the plan's own explicit `tier`/`required` column, if present; **(2)** a matching event+parameter entry in the bundled default GA4 spec, borrowing its tier/required (real curated data, not a guess — why an ordinary Sheets export with just event/param/description columns still comes out sensibly tiered); **(3)** cautious keyword inference from the `notes`/`description` column as a last resort — looking for "required"/"mandatory" (checking first for negation like "not required" or the word "optional"), and inferring CRITICAL when the note also signals real severity ("critical", "high impact", "breaks reporting/revenue"). Any CRITICAL finding resolved this way is automatically flagged inline as "(tier inferred from notes — verify)" — no extra step needed on your end.
- This fallback logic only applies to the CSV/TSV/Excel/flat-JSON-record tracking plan shapes. If a user hands you the native `{"events": {...}}` JSON shape (matching the bundled spec's own format), it's taken as fully-specified as written — no inference layered on top.

### Step 4: Render the In-Chat Markdown Report

Read the JSON's `event_reports` (not the granular `findings`) and render an in-chat report, one block per event, grouped by severity:

```markdown
# GA4 Tracking Audit

**Tracking plan:** [bundled default | user's plan, named]
**Observed data:** [format detected, e.g. "flat gtag.js capture, 3 event types"]
**Totals:** 🔴 N critical · 🟡 N warning · 🔵 N notice

## 🔴 purchase — 1 occurrence affected
- Missing `transaction_id`, `currency` (event-scoped)
- Missing `item_name` (item-scoped)
- `price` sent as string ("149.00") instead of a number

**Fix:**
```js
<suggested_fix from the event_reports entry>
```

## 🔵 page_view — 1 occurrence affected
...
```

Use each event report's `suggested_fix` block verbatim (or lightly reformatted) as the copy-pasteable `dataLayer.push` fix — it already merges valid observed values, missing-field placeholders, and corrected replacements for wrong-typed fields into one block, so don't reconstruct it by hand from the individual issues. When `occurrences_affected` is greater than 1, state the count (e.g. "affects 214 of 340 purchase events") so the user can tell a one-off from a systemic tagging bug. A CRITICAL finding whose tier came from notes-inference already carries a "(tier inferred from notes — verify)" caveat in its issue text — just pass it through as-is. Keep this report conversational and scannable, since it's a chat response rather than a document.

### Step 5: Generate the Excel Findings Workbook

You have two ways to produce this, and either is fine:

- **Build it yourself** from `event_reports` using `openpyxl`/`pandas` and whatever xlsx-authoring guidance your environment provides — this gives you full control over formatting and is the better choice when you're already presenting the workbook back through this environment.
- **Let the script write it directly** by re-running Step 3 with `--excel-output <path>` (e.g. `--excel-output /tmp/findings.xlsx`). This produces a workbook from `event_reports` with the columns below, color-coded by severity, and needs only `openpyxl` (not `pandas`). This is the simpler option for non-interactive or standalone runs of this script.

Either way, structure the workbook as **one row per individual issue, grouped by event** — not one giant cell per event with every issue crammed in via newlines. Lightweight previewers (including in-chat file viewers) often don't auto-size row height for wrapped multi-line cells, so a cell packed with many newline-joined bullets tends to render as clipped/garbled rather than actually wrapping, even though it looks fine once downloaded and opened in desktop Excel. Columns:

`Severity | Event | Occurrences Affected | Issue | Suggested Fix`

Merge the Event, Occurrences Affected, and Suggested Fix cells vertically across each event's group of issue-rows (so those appear once per event, not once per issue), and set explicit row heights rather than relying on auto-fit. `write_excel_findings()` in the script already does exactly this — matching its structure if you build the workbook yourself avoids reintroducing the rendering problem. Preserve the CRITICAL → WARNING → NOTICE ordering already present in the JSON. Save the file to whatever output location or working directory your environment uses for user-facing deliverables, and deliver it however that environment surfaces files to the user (a download link, a file-share tool, or just the file path)—alongside the Markdown report, so the user gets both the fast in-chat read and a shareable, sortable artifact for their team.

If someone specifically wants the fully granular, one-row-per-parameter view instead (e.g. for further programmatic filtering), build it from the JSON's `findings` array — it's still there, unchanged in shape from before, just no longer the primary view for the human-facing report.

---

## Reference Files

- `references/ga4-event-spec-reference.md` — Human-readable documentation of the full bundled default spec: every event, parameter, tier, and the reasoning behind each tier. Read this when the user asks *why* something is tiered a certain way, or wants help extending the default spec with a custom event.
- `references/ga4-default-spec.json` — Machine-readable twin of the above that `scripts/validate_schema.py` actually loads at runtime (and also uses as layer 2 of the tracking-plan fallback described in Step 3). Keep both files in sync if either is edited.
