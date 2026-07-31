# GA4 Analytics Data Quality Suite

A practical toolkit designed to find and fix common Google Analytics 4 (GA4) data issues—before and after you launch your campaigns.

Whether you are trying to figure out why traffic is landing in **Unassigned**, cleaning up dirty marketing links, or double-checking that your web analytics events are firing correctly, this suite automates the tedious cleanup work.

---

## 📌 What’s Included?

This repository contains two complementary auditing tools:

### 1. 🔗 UTM Campaign Taxonomy Auditor
**Fixes messy campaign links and prevents broken traffic attribution.**

Marketing links with typos, uppercase letters, or missing details break your reporting. This auditor checks your campaign URLs in bulk, flags problems, and hands back a clean list of corrected links ready to paste.

* **Fixes "Unassigned" Traffic:** Catches missing information or typos (`ppc` instead of `cpc`) before links go live.
* **Cleans Up Duplicate Rows:** Combines split traffic caused by inconsistent capitalization (e.g., `Facebook` vs. `facebook`).
* **Catches Unfilled Templates:** Flags broken links like `utm_source={source_name}` that were published by mistake.

---

### 2. 📊 GA4 Schema & Tracking Auditor
**Checks if your website events and ecommerce tracking match your plan.**

Compares actual website data (from Google Tag Manager, BigQuery, or GA4 exports) against your tracking blueprint or standard GA4 guidelines.

* **Missing Data Alerts:** Flags missing ecommerce fields (like `price` or `quantity` on purchases).
* **Formatting Checks:** Finds subtle errors like numbers sent as text (`"49.99"` instead of `49.99`).
* **Item-Level Auditing:** Checks individual products inside shopping cart and checkout events.

---

## 🚦 How Issues Are Categorized

Both tools organize findings into three simple levels so you know what to fix first:

| Level | Severity | What It Means | Impact |
| :--- | :---: | :--- | :--- |
| **CRITICAL** | 🔴 | **Broken Tracking** | Missing required information or unparseable URLs. Causes traffic to land in **Unassigned** or breaks revenue totals. |
| **WARNING** | 🟡 | **Incorrect Category** | Mismatched names or data formats. Traffic gets tracked, but ends up in the wrong report or bucket. |
| **NOTICE** | 🔵 | **Formatting Drift** | Minor inconsistencies like capitalization. Splits one clean report line into multiple separate rows. |

---

## 📁 Repository Structure

```text
ga4_analytics-data-quality-suite/
├── README.md
├── utm-campaign-taxonomy-auditor/
│   ├── SKILL.md                          # Auditor guide & instructions
│   ├── scripts/validate_utm.py           # Campaign URL checker engine
│   └── references/                       # Standard channel guidelines
└── ga4-schema-tracking-auditor/
    ├── SKILL.md                          # Auditor guide & instructions
    ├── scripts/validate_schema.py        # Event tracking checker engine
    └── references/                       # Standard GA4 event specifications
