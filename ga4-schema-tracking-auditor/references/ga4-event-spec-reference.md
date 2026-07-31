# GA4 Default Event & Parameter Spec Reference

This is the bundled fallback tracking plan used by the `ga4-schema-tracking-auditor` skill
whenever the user doesn't supply their own tracking plan. It covers GA4's standard
web-analytics events plus the recommended ecommerce events, with each parameter tiered by
how much damage its absence or corruption does to reporting.

The machine-readable version of this same spec lives in `ga4-default-spec.json` and is what
`scripts/validate_schema.py` actually loads. If you edit one, edit the other — they're meant
to stay in sync.

## Severity tiers

| Tier | Meaning |
|---|---|
| 🔴 CRITICAL | Missing this parameter (or getting its type badly wrong) breaks core GA4 processing or a core conversion/revenue report — e.g. no `transaction_id` on `purchase` means duplicate or lost revenue; no `search_term` on `search` means the event carries no signal at all. |
| 🟡 WARNING | A data type mismatch, or a missing optional/recommended parameter that degrades a standard report but doesn't break it — e.g. `value` sent as the string `"49.99"` instead of the number `49.99`, or a missing `item_category`. |
| 🔵 NOTICE | Naming/casing drift (e.g. `pageLocation` instead of `page_location`) that fragments reports because GA4 treats differently-cased parameter names as different parameters, even though nothing is technically "broken." |

**Tier vs. "required"** — these answer two different questions. Tier says *how bad it is if this parameter is wrong*. A separate `required` flag (defaulting to `true` for every parameter unless stated otherwise) says *whether its absence is even worth flagging at all*. Almost every parameter in this spec is required — the rare exception is something like `quantity` on `view_item`, which is 🟡 WARNING-tier *if* it's present and wrong, but isn't required, so a `view_item` event that correctly never sends it produces no finding at all.

---

## Standard web analytics events

### `page_view`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `page_location` | 🔴 CRITICAL | string | Full page URL. Missing it breaks the Pages and Landing Page reports. |
| `page_title` | 🟡 WARNING | string | Powers the Page Title dimension. |
| `page_referrer` | 🟡 WARNING | string | Feeds referral/session-source attribution. |
| `language` | 🔵 NOTICE | string | Recommended for locale breakdowns. |

### `generate_lead`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `value` | 🔴 CRITICAL | float | Needed for lead value / ROAS reporting. |
| `currency` | 🔴 CRITICAL | string | Required any time `value` is sent (ISO 4217, e.g. `USD`). |
| `form_id` | 🟡 WARNING | string | Lets you break leads out by form. |
| `form_name` | 🟡 WARNING | string | Human-readable form label for reporting. |
| `lead_source` | 🔵 NOTICE | string | Common custom param for channel segmentation. |

### `sign_up`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `method` | 🟡 WARNING | string | e.g. `Google`, `email` — compares signup methods. |

### `login`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `method` | 🟡 WARNING | string | Same idea as `sign_up`. |

### `search` / `view_search_results`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `search_term` | 🔴 CRITICAL | string | Without it, the event has no analytical value and the Search Terms report is empty. |

### `file_download`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `file_name` | 🔴 CRITICAL | string | Identifies which file was downloaded. |
| `file_extension` | 🟡 WARNING | string | Enables breakdowns by file type. |
| `link_url` | 🔵 NOTICE | string | Full URL of the file. |
| `link_text` | 🔵 NOTICE | string | Anchor text of the link. |

### `click` (outbound link tracking)
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `link_url` | 🔴 CRITICAL | string | Required to know what was actually clicked. |
| `link_domain` | 🟡 WARNING | string | Needed for outbound-click breakdowns. |
| `outbound` | 🟡 WARNING | bool | Distinguishes outbound vs. internal clicks. |

### `video_start`, `video_progress`, `video_complete`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `video_title` | 🟡 WARNING | string | Identifies the video. |
| `video_percent` | 🟡 WARNING | int | (progress only) Which milestone fired. |
| `video_url` / `video_provider` | 🔵 NOTICE | string | Extra context. |

### `form_start`, `form_submit`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `form_id` | 🟡 WARNING | string | Identifies the form. |
| `form_name` | 🟡 WARNING | string | Human-readable label. |
| `form_submit_text` | 🔵 NOTICE | string | Label of the submit button. |

### `scroll`
| Parameter | Tier | Type | Why |
|---|---|---|---|
| `percent_scrolled` | 🟡 WARNING | int | Which scroll milestone fired. |

---

## Recommended ecommerce events

All ecommerce events share the same `items[]` array shape. Parameters below marked "items"
apply per-item (item-scoped), everything else is event-scoped.

### `view_item_list` / `select_item`
| Parameter | Scope | Tier | Type |
|---|---|---|---|
| `item_list_id` / `item_list_name` | event | 🟡 WARNING | string |
| `item_id` | item | 🟡 WARNING | string |
| `item_name` | item | 🔴 CRITICAL | string |
| `item_category` | item | 🟡 WARNING | string |
| `price` | item | 🟡 WARNING | float |
| `index` | item | 🔵 NOTICE | int |

### `view_item`

`quantity` is marked **optional** below — GA4 doesn't require a quantity just to view an item, but plenty of ecommerce platforms pass one by default anyway since the item object schema is shared across events. The auditor only checks it when present (type/casing), and never nags about it being absent.

| Parameter | Scope | Tier | Type | Required? |
|---|---|---|---|---|
| `currency` | event | 🔴 CRITICAL | string | Yes |
| `value` | event | 🟡 WARNING | float | Yes |
| `item_id` | item | 🟡 WARNING | string | Yes |
| `item_name` | item | 🔴 CRITICAL | string | Yes |
| `item_category` | item | 🟡 WARNING | string | Yes |
| `price` | item | 🔴 CRITICAL | float | Yes |
| `item_brand` | item | 🔵 NOTICE | string | Yes |
| `quantity` | item | 🟡 WARNING | int | **No** — checked for type only if present |

### `add_to_wishlist`

| Parameter | Scope | Tier | Type | Required? |
|---|---|---|---|---|
| `currency` / `value` | event | 🟡 WARNING | string / float | Yes |
| `item_id` | item | 🟡 WARNING | string | Yes |
| `item_name` | item | 🔴 CRITICAL | string | Yes |
| `price` | item | 🟡 WARNING | float | Yes |
| `quantity` | item | 🟡 WARNING | int | **No** — checked for type only if present |

### `add_to_cart` / `remove_from_cart` / `view_cart`
| Parameter | Scope | Tier | Type |
|---|---|---|---|
| `currency` | event | 🔴 CRITICAL (add_to_cart) / 🟡 WARNING (others) | string |
| `value` | event | 🔴 CRITICAL (add_to_cart) / 🟡 WARNING (others) | float |
| `item_id` | item | 🟡 WARNING | string |
| `item_name` | item | 🔴 CRITICAL | string |
| `item_category` | item | 🟡 WARNING | string |
| `price` | item | 🔴 CRITICAL (add_to_cart) / 🟡 WARNING (others) | float |
| `quantity` | item | 🟡 WARNING | int |

### `begin_checkout`
| Parameter | Scope | Tier | Type |
|---|---|---|---|
| `currency` | event | 🔴 CRITICAL | string |
| `value` | event | 🔴 CRITICAL | float |
| `coupon` | event | 🔵 NOTICE | string |
| `item_id` | item | 🟡 WARNING | string |
| `item_name` | item | 🔴 CRITICAL | string |
| `price` | item | 🔴 CRITICAL | float |
| `quantity` | item | 🟡 WARNING | int |

### `add_shipping_info` / `add_payment_info`
| Parameter | Scope | Tier | Type |
|---|---|---|---|
| `currency` / `value` | event | 🟡 WARNING | string / float |
| `shipping_tier` (shipping) / `payment_type` (payment) | event | 🔵 NOTICE | string |
| `item_id` | item | 🟡 WARNING | string |
| `item_name` | item | 🔴 CRITICAL | string |
| `price` | item | 🟡 WARNING | float |
| `quantity` | item | 🟡 WARNING | int |

### `purchase`
| Parameter | Scope | Tier | Type | Why |
|---|---|---|---|---|
| `transaction_id` | event | 🔴 CRITICAL | string | Missing → duplicate/undercounted revenue, breaks dedup. |
| `value` | event | 🔴 CRITICAL | float | Must be numeric, never a currency-formatted string like `"$49.99"`. |
| `currency` | event | 🔴 CRITICAL | string | Required whenever `value` is sent. |
| `tax` / `shipping` | event | 🟡 WARNING | float | |
| `coupon` | event | 🔵 NOTICE | string | |
| `item_id` | item | 🟡 WARNING | string | |
| `item_name` | item | 🔴 CRITICAL | string | |
| `item_category` | item | 🟡 WARNING | string | |
| `price` | item | 🔴 CRITICAL | float | |
| `quantity` | item | 🔴 CRITICAL | int | Missing silently distorts revenue-per-item math. |
| `item_brand` / `item_variant` / `coupon` (item) | item | 🔵 NOTICE | string | |

### `refund`
| Parameter | Scope | Tier | Type |
|---|---|---|---|
| `transaction_id` | event | 🔴 CRITICAL | string |
| `value` / `currency` | event | 🟡 WARNING | float / string |
| `item_id` / `item_name` | item | 🟡 WARNING | string |
| `quantity` | item | 🟡 WARNING | int |

---

## Notes on casing drift

GA4 treats parameter names as case-sensitive strings. `pageLocation`, `Page_Location`, and
`page_location` are three *different* parameters as far as GA4's processing is concerned —
even though they're "the same thing" to a human reading a tracking plan. This is the single
biggest source of quiet report fragmentation, because none of these produce an error; they
just each accumulate a fraction of the data under a different name, and none of them show up
as the "real" parameter in standard reports.

The auditor normalizes names (case + separator agnostic) purely to *match* an observed
parameter against the spec — it still flags the drift itself as a 🔵 NOTICE finding with the
exact rename needed to fold the data back into a single, correctly-cased parameter going
forward.
