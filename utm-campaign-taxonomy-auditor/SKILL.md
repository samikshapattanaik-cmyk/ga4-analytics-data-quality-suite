---
name: utm-campaign-taxonomy-auditor
description: Audits batches of campaign URLs for broken or messy UTM tagging that causes "Unassigned" traffic and duplicate rows in GA4. Use this whenever the user pastes or uploads a list of campaign URLs (from Google Sheets, Excel, CSV, a GA4 acquisition export, or a raw copy-pasted list) and wants them checked, validated, cleaned, or fixed. Also trigger on requests to audit UTM parameters, validate utm_source/utm_medium/utm_campaign, fix GA4 Unassigned traffic, align URLs to a channel/source-medium taxonomy, catch casing inconsistencies (Facebook vs facebook), catch medium synonym collisions (ppc vs cpc, email vs e-mail, paidsocial vs paid-social), catch double-encoded URLs (%2520), or catch unreplaced template tags like {campaign_name} or {{source}} in marketing links. Trigger even if the user just says something like "can you check these campaign links before we launch" or "why is GA4 showing so much Unassigned traffic."
---

# UTM Campaign Taxonomy Auditor

## What this skill does and why it matters

Every campaign URL is a data-entry event. A single typo in `utm_medium` (`ppc` instead of `cpc`), a stray capital letter (`Facebook` instead of `facebook`), or a template variable that never got filled in (`utm_source={source_name}`) doesn't just look sloppy — it silently fragments GA4 reporting. Rows that should roll up into one channel get split into several, and URLs GA4 can't parse at all get dumped into "Unassigned." This skill catches those problems before the links go live, or diagnoses them after the fact from a GA4 export, and hands back both a readable report and a spreadsheet of corrected links.

The actual parsing and rule-checking is deterministic (same URL in, same verdict out), so it's delegated to a bundled Python script rather than eyeballed. Your job is to gather the inputs, run the script, and turn its structured output into the two deliverables the user actually wants.

## Step 1: Setup questions

Before running anything, ask the user (in one message, not one at a time):

1. **Taxonomy**: "Do you have your own source/medium taxonomy or casing convention (pasted from Google Sheets, or an allowed-values list), or should I use the standard GA4 Default Channel Grouping baseline?" If they don't have one, use `references/utm-taxonomy-standards.md` as the fallback — don't ask them to produce one from scratch.
2. **URL batch location**: "Is your batch of URLs pasted directly / uploaded as a file, or does it live in a database or tool I'd need to query?" If it's a database or tool, confirm the exact database/table name and the column(s) holding the raw URLs or UTM parameters *before* running anything — never guess at a schema.

Don't skip ahead to Step 2 until you have real answers to both, or the user tells you to just use defaults.

## Step 2: Data ingestion & path handling

Get the URL batch onto disk in a form the script can read:

- **Pasted text**: write it to a `.txt` or `.csv` file yourself (one URL per line, or preserve whatever ID column the user gave you).
- **Uploaded file** (.csv, .xlsx, GA4 export): use the path directly.
- **Database/tool**: only after the user has confirmed table/column names in Step 1 — pull the rows and write them to a local CSV before proceeding.

If a taxonomy was provided, save it alongside as a JSON file (see `--taxonomy` format in the script's `--help`) or point the script at the pasted taxonomy text. If none was provided, don't pass `--taxonomy` at all — the script falls back to the GA4 baseline built into it.

**Never fabricate URLs.** If the file can't be found, can't be opened, or is empty, stop and tell the user exactly what went wrong (see the script's error handling below) rather than inventing example rows to keep going.

## Step 3: Script execution

Run the bundled script. The path below (`scripts/validate_utm.py`) is relative to this skill's own directory, not wherever you happen to be running from — resolve it against the skill's installed location (e.g. `<skill-dir>/scripts/validate_utm.py`) rather than assuming the current working directory:

```bash
python3 <skill-dir>/scripts/validate_utm.py --input <path-to-urls> [--taxonomy <path-to-taxonomy.json>] --output <path-to-results.json>
```

The script:
- Reads `.csv`, `.xlsx`/`.xlsm`, or plain `.txt` (one URL per line) input, wrapped in try/except so a bad file produces a clear, specific error instead of a crash or silent skip.
- Parses `utm_source`, `utm_medium`, `utm_campaign` (and any other `utm_*` params present) out of each URL with `urllib.parse`, automatically detecting and unwinding double-encoding (`%2520` → `%20` → space, etc.).
- Checks each parsed value against the taxonomy (allowed lists, canonical casing, synonym map) and against structural rules (missing required params, unreplaced template placeholders, malformed query strings).
- Tiers every issue found as 🔴 CRITICAL, 🟡 WARNING, or 🔵 NOTICE (see below).
- Builds a corrected destination URL wherever the fix is unambiguous (casing, known synonym, decoding), and leaves a placeholder plus an explicit flag wherever it isn't (e.g. a template tag with no way to know the intended value).
- Writes one JSON object to `--output` (or stdout if omitted) with a summary count and one entry per URL.

If the script exits with an error, relay the exact message to the user along with the suggested fix it prints — don't paraphrase it into something vaguer, and don't attempt the audit with partial or synthetic data.

### Severity tiers (for your own reference when reading the JSON and writing the report)

- 🔴 **CRITICAL** — unfilled template tags (`utm_source={source_name}`, `utm_campaign={{campaign}}`), missing `utm_source`, or a URL that doesn't parse as valid at all. These rows won't attribute *at all* — they're the ones most likely showing up as Unassigned right now.
- 🟡 **WARNING** — medium synonym collisions that GA4's channel grouping doesn't recognize (`ppc` instead of `cpc`, `e-mail` instead of `email`, `paidsocial` instead of `paid-social`), double-encoding artifacts (`%2520`), or a missing `utm_medium`/`utm_campaign`. These often still get *some* attribution, just the wrong bucket, or land in Unassigned depending on the exact GA4 rule matched.
- 🔵 **NOTICE** — casing drift (`Facebook` vs `facebook`) that GA4 treats as a different row entirely, quietly splitting one channel's reporting into two or more.

## Step 4: In-chat Markdown report

Render the findings directly in the conversation — don't make the user open a file to see what's wrong. Structure:

```markdown
# UTM Audit Summary
[N] URLs checked · [X] 🔴 Critical · [Y] 🟡 Warning · [Z] 🔵 Notice · [W] clean

## 🔴 Critical
- **[id/short URL]** — [issue]. Fix: [what needs to happen, e.g. "replace {source_name} with the actual source"]

## 🟡 Warning
- **[id/short URL]** — [issue] → corrected to `[value]`

## 🔵 Notice
- **[id/short URL]** — [issue] → corrected to `[value]`
```

Group by tier, most severe first. For each finding, state the specific parameter and value, not just "this URL has an issue." If a tier has zero findings, say so briefly rather than omitting the section — the user should be able to tell at a glance that nothing critical is lurking. Keep this conversational and scannable; save the exhaustive row-by-row detail for the Excel file in Step 5.

## Step 5: Excel artifact with corrected URLs

If `/mnt/skills/public/xlsx/SKILL.md` exists in this runtime, read it first and follow its guidance for creating the workbook. If that path isn't present (some runtimes don't bundle it), fall back to building the workbook directly with `openpyxl` (or `pandas` if already available) — the column layout below is all you need either way.

Build a workbook from the script's JSON output with (at minimum) these columns:

| Column | Content |
|---|---|
| ID | row ID or index from the input |
| Original URL | as provided |
| Severity | worst tier found for that row, or "OK" |
| Issues | one-line, semicolon-separated summary of every issue on that row |
| Corrected URL | the script's fixed URL, ready to copy-paste; blank/flagged where a human decision is required (e.g. an unfilled template tag) |

Sort rows Critical → Warning → Notice → OK so the highest-priority fixes are at the top. Save the file and share it with `present_files` alongside the in-chat report — the user needs both the quick read and the working file.

## Notes on iterating

If the user pushes back on a tiering decision (e.g. they consider `ppc` acceptable in their org), that's a taxonomy customization, not a bug — help them encode it into a taxonomy JSON file (per Step 1/2) so future runs respect it, rather than special-casing it in the script itself.
