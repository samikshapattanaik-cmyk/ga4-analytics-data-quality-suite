---
name: ga4-schema-tracking-auditor
description: Audits GA4 event tracking for drift against a tracking plan—catches missing required parameters, data type mismatches (e.g. "49.99" instead of 49.99), and casing drift (e.g. pageLocation vs page_location) across both standard web analytics events (page_view, generate_lead, sign_up, search, login, file_download) and ecommerce events (view_item, add_to_cart, begin_checkout, purchase), including item-scoped parameters inside the items[] array. Use this whenever the user wants to QA, validate, or audit their GA4 tracking implementation, check a GA4 BigQuery export, GTM Preview dump, Data API pull, or tracking plan spreadsheet for tagging errors, investigate why GA4 reports look fragmented or incomplete, or reconcile an analytics tracking plan against production data.
---
 
# GA4 Schema & Tracking Auditor
 
This skill compares observed GA4 events against a reference tracking plan, reporting gaps according to three severity tiers:
 
- 🔴 **CRITICAL:** Missing mandatory event/parameter required for core GA4 processing or revenue reporting.
- 🟡 **WARNING:** Data type mismatch or missing optional/recommended parameter.
- 🔵 **NOTICE:** Naming/casing drift that fragments reports without outright breaking tracking.
All parsing, unnesting, and diffing logic is executed deterministically via `scripts/validate_schema.py`.
 
---
 
## Workflow Execution Steps
 
### Step 1: Confirm Setup & Input Sources
 
Before executing the script, confirm the input sources with the user:
 
1. **Tracking Plan:** "Do you have your own tracking plan (Google Sheets paste, CSV, Excel, or JSON), or should I use the bundled GA4 default spec covering standard web and ecommerce events?"
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
- The script auto-detects the observed data format: BigQuery-style export (rows with `event_name`/`event_params`/`items`), GTM Preview/dataLayer JSON dump, GA4 Data API JSON pull (rows + dimensionHeaders), or tabular CSV/TSV/Excel. If detection isn't confident, it exits with an error instead of guessing—pass `--format bq_json`, `--format gtm_preview_json`, `--format ga4_api_json`, or `--format tabular` to force it.
- **Dependencies:** JSON, JSONL, CSV, and TSV need nothing beyond the Python standard library—this covers every Google Sheets export, since Sheets always downloads as CSV/TSV. `pandas` + `openpyxl` are only imported, and only needed, when the file is a genuine binary Excel workbook (`.xlsx`/`.xls`). If the script reports them missing for an Excel input, the simplest fix is usually to ask the user to re-export the same file as CSV instead (Google Sheets/Excel: File > Download > CSV)—no dependency involved. If they specifically need the Excel file read as-is, install the two packages using whatever approach fits the environment (a virtualenv, `pip install pandas openpyxl`, or that same command with `--break-system-packages` if the environment's Python blocks unmanaged installs) and retry once.
- If a custom tracking plan is supplied, it needs at minimum an `event_name` column and a `param_name` column (CSV/TSV/Excel), or an equivalent flat JSON list of records. Optional columns: `scope` (`event`|`item`, defaults to `event`), `tier` (`CRITICAL`|`WARNING`|`NOTICE`, defaults to `WARNING`), `data_type` (`string`|`int`|`float`|`bool`, defaults to `any`), `notes`. If column names or layout are ambiguous, confirm the mapping with the user rather than guessing—a wrong guess silently changes which issues get flagged as CRITICAL vs WARNING.
### Step 4: Render the In-Chat Markdown Report
 
Read the JSON findings and render an in-chat report, grouped by severity then by event:
 
```markdown
# GA4 Tracking Audit
 
**Tracking plan:** [bundled default | user's plan, named]
**Observed data:** [format detected, e.g. "BigQuery export, 3 event types"]
**Totals:** 🔴 N critical · 🟡 N warning · 🔵 N notice
 
## 🔴 Critical
- **`purchase`** — missing `quantity` on N item(s)
  Fix: `<suggested_fix from JSON>`
 
## 🟡 Warning
...
 
## 🔵 Notice
...
```
 
Use each finding's `suggested_fix` field verbatim (or lightly cleaned up) as the copy-pasteable GTM variable/dataLayer snippet—don't invent fix language that contradicts what the script computed. When `occurrences_affected` is greater than 1, state the count (e.g. "affects 214 of 340 purchase events") so the user can tell a one-off from a systemic tagging bug. Keep this report conversational and scannable, since it's a chat response rather than a document.
 
### Step 5: Generate the Excel Findings Workbook
 
You have two ways to produce this, and either is fine:
 
- **Build it yourself** using `openpyxl`/`pandas` and whatever xlsx-authoring guidance your environment provides — this gives you full control over formatting and is the better choice when you're already presenting the workbook back through this environment.
- **Let the script write it directly** by re-running Step 3 with `--excel-output <path>` (e.g. `--excel-output /tmp/findings.xlsx`). This produces a workbook with the same columns below, color-coded by severity, and needs only `openpyxl` (not `pandas`). This is the simpler option for non-interactive or standalone runs of this script.
Either way, the workbook should have one row per finding, with columns:
 
`Severity | Event | Scope | Parameter | Issue | Expected | Observed | Occurrences Affected | Suggested Fix`
 
Preserve the CRITICAL → WARNING → NOTICE ordering already present in the JSON. Save the file to whatever output location or working directory your environment uses for user-facing deliverables, and deliver it however that environment surfaces files to the user (a download link, a file-share tool, or just the file path)—alongside the Markdown report, so the user gets both the fast in-chat read and a shareable, sortable artifact for their team.
 
---
 
## Reference Files
 
- `references/ga4-event-spec-reference.md` — Human-readable documentation of the full bundled default spec: every event, parameter, tier, and the reasoning behind each tier. Read this when the user asks *why* something is tiered a certain way, or wants help extending the default spec with a custom event.
- `references/ga4-default-spec.json` — Machine-readable twin of the above that `scripts/validate_schema.py` actually loads at runtime. Keep both files in sync if either is edited.
