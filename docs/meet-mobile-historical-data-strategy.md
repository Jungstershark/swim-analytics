# Meet Mobile Historical Data Strategy

Status: **KIV / strategic context**  
Current priority remains: official-source ingestion, longitudinal swimmer/coach/club analytics, and production data quality.

## Why this exists

Meet Mobile is useful strategic context because it is the incumbent result-distribution surface in many swim meets. The goal is **not** to make Swim Analytics dependent on Meet Mobile scraping. The goal is to understand its moat, learn from its information architecture, and possibly use user-provided visible app data as a bounded secondary source for historical backfill or comparison.

## Product thesis

Meet Mobile appears dominant less because consumers love the app and more because it sits in the meet-day data distribution path:

```text
meet operations / HY-TEK / host publishing
→ Meet Mobile availability
→ parents, swimmers, coaches use the app because the live meet data is there
```

Swim Analytics should not first compete by being “Meet Mobile but prettier.” The stronger wedge is:

```text
Meet Mobile tells users what happened at a meet.
Swim Analytics should tell swimmers, coaches, clubs, and admins what the results mean over time.
```

## Current strategic focus

Focus on one thing and do it well:

1. Build a source-honest official-results archive.
2. Ingest official PDFs and event pages as canonical data.
3. Build longitudinal capabilities:
   - swimmer history;
   - PB progression;
   - event-specific trends;
   - split analysis;
   - prelim/final comparison;
   - qualifying-cut proximity;
   - club/team performance;
   - NSA/admin overview.
4. Later work backward toward live meet operations or vertical-stack integration only if the data/product wedge proves valuable.

## Meet Mobile moat hypothesis

| Layer | Hypothesis | Implication |
|---|---|---|
| B2B workflow | Meet hosts/timing operators publish from incumbent meet software workflows | Consumer app alternatives have no data unless they win the host workflow |
| Event urgency | Users need results during the meet now | Mediocre UX can still win if it has the only timely data |
| Familiar IA | Meet → event/session → heat/result → swimmer/team | We should respect this baseline information architecture |
| Closed access | No public API; data access is app/platform-controlled | Avoid depending on unauthorized or brittle internal access |
| Consumer frustration | Subscriptions/paywalls/UX issues create resentment | Opportunity exists if we offer trustworthy, cheaper, better longitudinal value |

These are hypotheses to verify with real users, meet hosts, coaches, and public documentation before making business commitments.

## Historical data backfill options

### Preferred / canonical

Use official and user-provided source files:

- federation PDFs;
- official event result pages;
- HY-TEK exports where voluntarily provided;
- club/coach uploaded PDFs/ZIPs;
- future documented timing/meet-management exports.

Mark these as canonical when source authority is strong:

```text
source_type = sg_aquatics_pdf | club_official_upload | hytek_export
source_authority = official | operator_provided
canonical = true
```

### Secondary / bounded

If Jung Yi provides access to his own Meet Mobile app/account, visible-app capture can be used as a **secondary, non-canonical** historical source:

```text
source_type = meet_mobile_user_capture
source_authority = secondary
canonical = false
capture_method = android_visible_screen_ui_tree | android_visible_screen_ocr
```

Use cases:

- benchmark Meet Mobile information architecture;
- compare our parsed official data against what users see;
- recover temporary historical gaps;
- prototype swimmer-history UX;
- investigate whether splits exist in app but not in official PDFs.

Do **not** use Meet Mobile capture as the permanent core pipeline.

## Low-token Android capture plan

If/when an Android device is prepared with USB debugging, use deterministic extraction before any LLM/OCR-heavy flow.

Preferred pipeline:

```text
Android device with legitimate Meet Mobile access
→ adb / uiautomator2 navigation
→ uiautomator XML dump of visible screen text and bounds
→ deterministic Python parser
→ screenshots saved for audit/fallback
→ local Tesseract OCR only when UI XML lacks text
→ structured JSON/CSV
→ import as secondary/non-canonical source
```

Tools:

| Tool | Role |
|---|---|
| `adb` | launch app, tap/swipe/type, screenshot, dump UI tree |
| `uiautomator dump` | extract visible text/bounds without LLM tokens |
| `uiautomator2` / Appium | repeatable navigation automation |
| Tesseract | local OCR fallback, zero LLM tokens |
| OpenCV | image preprocessing/table segmentation if needed |

Avoid by default:

- bypassing paywalls/authentication;
- stealing tokens/session data;
- breaking certificate pinning;
- patching APKs;
- pulling private app storage via root;
- redistributing Meet Mobile-derived bulk data as canonical product data.

## Legal / risk posture

This is not legal advice. ACTIVE’s public terms include restrictions against automated scraping/data mining and reverse engineering. Therefore:

- keep capture bounded to data Jung Yi can legitimately view;
- prefer visible-screen extraction over internal API interception;
- store provenance honestly;
- keep it secondary/non-canonical;
- avoid building a product dependency on Meet Mobile access;
- consult proper legal advice before any public/commercial use of Meet Mobile-derived data.

## Product benchmark gate

When ready, run a focused product/reviewer gate:

| Reviewer | Question |
|---|---|
| Competitive swimmer | Can I find my swims and understand progress faster than Meet Mobile? |
| Coach | Can I compare athletes/events and make useful decisions? |
| Club/admin | Can I see team performance and data quality clearly? |
| NSA/admin | Can I aggregate official results with provenance? |
| Product/UX | Is the IA cleaner than Meet Mobile’s meet/event/swimmer flow? |
| Data/domain | Does the model preserve meet/session/event/source meaning? |

Expected follow-up artifacts:

- `docs/product-benchmark-meet-mobile.md`
- `docs/swim-analytics-information-architecture.md`
- `docs/next-ui-slice-swimmer-meet-event-browser.md`

## Decision for now

KIV Meet Mobile extraction until Android access is prepared.

Continue current prod development:

1. validate SNAG import idempotency and provenance;
2. strengthen official-source ingestion;
3. build longitudinal swimmer/coach/club capabilities;
4. use Meet Mobile only as benchmark/secondary backfill where legally and technically appropriate.
