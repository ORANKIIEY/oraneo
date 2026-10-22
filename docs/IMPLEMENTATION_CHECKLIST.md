# Implementation checklist and audit trail

The starting ZIP was inspected before modification. Baseline: **5/5** Pytest tests passed. Original `fact_sales` contained 951 records, 49 rejected records, and an input file with 1,020 records (Indian-city synthetic dataset). The original repository contained a root CLI ETL, generator, chart utility, analytics SQL, SQLite warehouse, five tests, and Python-only CI.

## Issues found

- [x] Duplicate order IDs removed *before* business validation, risking loss of valid later occurrences.
- [x] Duplicate records silently dropped, not retained as auditable rows.
- [x] Potential nonnumeric strings or missing identifiers not robustly checked; insufficient multi-rule rejection reporting.
- [x] Unconditional `to_sql(...,if_exists='replace')` creates potential destructive/nontransactional replacement and inconsistent warehouse on partial failure.
- [x] No persistent pipeline run metadata, failure handling, or concurrency protection.
- [x] No web API, browser UI, CSV upload inspection, pagination, or rejected CSV download.
- [x] No native text PDF reporting.
- [x] Indian-city sample did not match the user's South African data preference.
- [x] Python-only CI with minimal test coverage.

## Completed implementation

- [x] Copied the original raw CSV, clean CSV, and SQLite DB into `data/legacy/` without modifying their bytes.
- [x] Added a reproducible **synthetic South African** sample with ZAR prices; generated processed CSV and initial clean SQLite warehouse.
- [x] Refactored CLI ETL to call reusable strict CSV validator, business validator, auditable deduplicator, and transactional SQLite loader.
- [x] Defined exact input/unique/duplicate/accepted/rejected reconciliation.
- [x] Added persistent run statuses, logs, issues, reasons, missing-value counts, and failed-run retry API.
- [x] Added full FastAPI backend and versioned query/filter/analytics/download routes.
- [x] Added 6-page React interface navigation: Overview, Pipeline, Explorer, Data quality, Run history, Reports.
- [x] Added ReportLab Platypus PDF generator with native text, repeat-header tables, vector revenue chart, pagination and methodological annotations.
- [x] Added local-safe uploads, whitelist sorting, parameterized SQL, controlled report downloads and environment settings.
- [x] Added Pytest backend tests (ETL, duplicates, integrity, API, malformed inputs, PDF and pagination).
- [x] Added Vitest/React Testing Library test source, TypeScript config, ESLint config, Vite config, and CI.
- [x] Replaced old Indian chart image with South African city overview.
- [x] Rewrote README with PowerShell commands and backup guidance.

## Verification

- [x] Baseline Pytest: 5 tests passed.
- [x] New Pytest suite: 28 tests passed.
- [x] Standalone local Uvicorn server HTTP health and dashboard tested successfully.
- [x] Sample warehouse validated: 1,020 input = 936 accepted + 64 rejected + 20 duplicates.
- [x] SQLite rollback, repeated-run replacement, old-database migration, and interrupted-status recovery covered by tests.
- [x] ReportLab reports extracted with pypdf and visually rendered for page layout checks.
- [x] Frontend TS/TSX files syntactically parsed with globally installed TypeScript compiler.
- [ ] Frontend runtime rendering, package installation, Vitest, ESLint, full typecheck and Vite build **not verified in this sandbox**: npm registry DNS resolution was unavailable. Run `npm install`, `npm run test`, `npm run lint`, `npm run typecheck`, and `npm run build` on a network-enabled workstation or CI.

The frontend is delivered as complete source code, not claimed as production-verified. The original data is kept only in `data/legacy/` for preservation and reference.

## ORANEO v2 additions
- [x] Rename product in navigation, page metadata, report headers and PDF downloads to ORANEO without adding a brand logo.
- [x] Add strictly square, solid-colour editorial CSS design with graphite navigation and orange accent.
- [x] Remove Recharts gradient definition; chart bars and line symbols are flat/square.
- [x] Add SQLite-persisted recurring local ETL schedule (disabled initially).
- [x] Add transaction-safe due-run claim, overlap protection, startup recovery and failure alerts.
- [x] Add configurable rejection and duplicate guardrails, acknowledgement and in-app alert centre.
- [x] Add explainable warehouse intelligence from the current snapshot, with freshness and a metric glossary.
- [x] Add real keyboard command palette and navigation alert count.
- [x] Expand Pytest to cover schedule/alerts/insights and manual ETL integration.
- [x] Generate ORANEO native-text PDF preview and render-check pages.
- [ ] Execute frontend test/type/lint/build commands after installing npm dependencies (network unavailable in current build container).
