
# UTM Taxonomy Standards (GA4 Default Channel Grouping Baseline)

Use this reference whenever the user doesn't supply their own taxonomy. It mirrors the
built-in defaults in `scripts/validate_utm.py` (`DEFAULT_TAXONOMY`) — if you change one,
change both.

GA4's Default Channel Grouping assigns each session to a channel based on rules that
look primarily at `utm_medium`, with `utm_source` and `utm_campaign` as secondary
signals. If `utm_medium` (or the whole UTM set) doesn't match a rule GA4 recognizes,
the session lands in **Unassigned** — which is the failure mode this skill exists to
prevent.

## Canonical `utm_medium` values

These are the values GA4's channel grouping rules actually key off of. Anything else —
including close synonyms — either matches the wrong channel or matches nothing.

| Canonical value | Channel it maps to | Common bad synonyms to catch |
|---|---|---|
| `cpc` | Paid Search | `ppc`, `paid`, `paidsearch`, `paid-search`, `cost-per-click` |
| `organic` | Organic Search | `seo`, `organic-search` |
| `email` | Email | `e-mail`, `e_mail`, `mail`, `newsletter` |
| `social` | Organic Social | `organic-social`, `organicsocial`, `social-organic` |
| `paid-social` | Paid Social | `paidsocial`, `paid_social`, `social-paid`, `socialpaid` |
| `referral` | Referral | — |
| `affiliate` | Affiliates | `aff`, `affiliates` |
| `display` | Display | `banner`, `banners`, `cpm` |
| `video` | Paid/Organic Video (context-dependent) | `paid-video`, `youtube-ads` |
| `sms` | SMS | `text` |
| `push` | Mobile Push Notifications | `push-notification` |
| `audio` | Audio | — |

**Rule of thumb:** if a medium value isn't in the left column, it's either a synonym
that needs remapping (right column, or something like it) or a genuinely custom medium
that belongs in the user's own taxonomy file, not the default one.

## Casing convention

GA4 does not normalize casing. `utm_source=Facebook` and `utm_source=facebook` are two
different rows in every report. The convention:

- All UTM parameter **values** should be lowercase.
- Use hyphens (`paid-social`) rather than underscores or camelCase for multi-word
  values, matching the canonical mediums above.
- Never use spaces — encode as `-` or `_`, never leave a raw space or `%20`/`%2520`.

## Required parameters

At minimum, every campaign URL should carry:

- `utm_source` — where the traffic originates (e.g. `google`, `facebook`, `newsletter`).
  Missing this is CRITICAL: GA4 has nothing to attribute the session to.
- `utm_medium` — the canonical medium from the table above. Missing or malformed this
  is a WARNING: the session may still get a source, but will likely be miscategorized
  or Unassigned.
- `utm_campaign` — the specific campaign name. Missing this is a WARNING: individual
  campaign performance can't be isolated even if the channel itself resolves correctly.

## Unfilled template variables

Marketing automation tools and spreadsheet formulas commonly leave placeholder syntax
in a URL when a merge/lookup fails, e.g.:

- `utm_source={source_name}`
- `utm_campaign={{campaign}}`
- `utm_content=%7Bad_id%7D` (URL-encoded curly braces)
- `utm_term=<<keyword>>`

These are always CRITICAL: the parameter isn't just wrong, it's literally the name of
a variable instead of a value, and GA4 will record that literal placeholder text as if
it were real data — polluting reports until someone notices.

## Double-encoding

A URL that's been encoded twice shows up as sequences like `%2520` (which is `%20`,
itself the encoding of a space, encoded again). This typically happens when a URL is
passed through more than one system that each apply their own encoding step (e.g. a
spreadsheet formula wrapping an already-encoded link, or a redirect service
double-wrapping a destination URL). Left as-is, GA4 sees the literal string `%2520`
in the parameter rather than decoding it to a space or the intended character,
producing malformed or unrecognizable parameter values.

## Notes on sources

Unlike medium, there's no fixed universe of valid `utm_source` values — sources are
whatever your actual partners and platforms are. If the user hasn't supplied an
allow-list, this skill only checks source casing consistency and any synonym pairs it's
told about (e.g. `fb` vs `facebook`), rather than restricting sources to a fixed list.
If the user wants a strict allow-list, that belongs in their own taxonomy JSON file
under `allowed_sources`.
