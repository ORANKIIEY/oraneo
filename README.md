# ORANEO · Data operations

An eight-screen, full-stack data operations platform for a **synthetic South African sales dataset**. ORANEO extends the original `sales-etl-pipeline` ETL implementation and preserves the previous warehouse and CSV files under `data/legacy/`. Synthetic amounts are configured as **ZAR**; they are not actual retail transaction records.

**Design:** Poppins typeface; pink (`#D9367E`), blush, graphite-plum and white; no logo, gradients, rounded corners or floating shadow cards. Components use clear data labels, meaningful error states and keyboard-accessible navigation. Google Fonts must be reachable to load Poppins; otherwise the sans-serif fallback is used.

## Features

| Screen | Working capability |
|---|---|
| Overview | Real warehouse KPIs, monthly revenue, products, city comparisons, quality metrics and execution history |
| Pipeline control | Validate an existing/uploaded CSV, run ETL asynchronously, poll status, inspect logs and retry failures |
| Sales explorer | Server-side pagination, search, dates, city, product, customer and sorting |
| Data quality | Row-level rejection and duplicate dispositions, original values, counts and safe CSV export |
| History | Persisted runs, statuses, metrics and execution logs |
| Reports | Native-text multi-page PDF analytics, quality and execution reports with filters |
| Automation | Configurable 15 min / hourly / 6-hourly / daily ETL; in-app quality threshold alerts |
| Warehouse insights | Explainable month comparisons, contributing cities/products and data freshness |

Keyboard shortcut: **Ctrl+K** or **Cmd+K** for fast navigation. All metrics are calculated by the Python API from SQLite, never invented in React. ETL snapshot semantics: a successful run **replaces the current facts**, while audit history stays available. The precise record reconciliation is `input = accepted + rejected + duplicates`.

## Requirements

- Python 3.11–3.13; Windows PowerShell or a Linux terminal.
- Node.js 22 and npm to develop or build the React frontend.
- An internet connection to install npm packages. The ZIP includes source, not `node_modules`.

## Windows setup — both servers with one command

**Important:** Open the **nested `oraneo` folder** that contains `start.py`, `requirements.txt`, `frontend` and `data`. Do not start in the outer ZIP extraction folder. This prevents an accidental empty SQLite database from being created in the wrong directory.

```powershell
cd "C:\path\to\extracted\oraneo"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python start.py
```

Or run `./start-oraneo.ps1` from PowerShell after installing the Python requirements. `start.py` checks `frontend/node_modules`, runs `npm install` on first use, and launches **FastAPI and Vite concurrently**. Ctrl+C stops both services. The command must be run with your Python virtual environment active, unless the `.ps1` wrapper locates `.venv` for you.

- Frontend: **http://localhost:5173**
- API documentation: **http://127.0.0.1:8000/docs**
- Health: **http://127.0.0.1:8000/api/v1/health**
- Diagnostic summary: **http://127.0.0.1:8000/api/v1/diagnostics**

Alternatively, use separate terminals from the `oraneo` root:

```powershell
# Terminal 1: FastAPI
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2: React/Vite (in the frontend subfolder)
cd frontend
npm install
npm run dev
```

**Run tests and quality checks** in separate environments:

```powershell
python -m pytest -q
cd frontend
npm run test
npm run lint
npm run typecheck
npm run build
```

The Vite dev server proxies `/api` to port 8000. A shared Axios client calls `/api/v1`, so it works unchanged when built frontend and API are hosted on the same Render URL. API links and OpenAPI links are relative (no `localhost` URLs in the deployed UI).

## Run ETL and generate a PDF

Use **Pipeline control** to preview and execute the bundled `data/raw/sales_raw.csv`, or upload a CSV with these columns: `order_id, order_date, customer_id, city, product, quantity, unit_price`.

CLI from project root:

```powershell
python -m src.etl --raw data/raw/sales_raw.csv --db data/warehouse.db --processed data/processed
```

Use **Reports** to select a report type and date filters, then click **Generate & download PDF**. ReportLab creates genuine PDF paragraphs, vector chart elements, searchable text and tables; not a dashboard screenshot.

## Render deployment — React + FastAPI + SQLite on one service

This package includes `Dockerfile`, `.dockerignore` and `render.yaml`. **One Render Web Service** runs FastAPI with **one worker** and serves the compiled Vite frontend from `frontend/dist`. No second frontend web service, no hardcoded API URL, and no multiple processes in production.

1. Create a GitHub repository, and push the **contents of the `oraneo` folder** so the repository root contains `Dockerfile` and `render.yaml`. The small, versioned demonstration seed is `data/seed/warehouse_seed.db`. Do **not** commit environment secrets, uploads or the working `data/warehouse.db`.
2. In Render, select **New → Blueprint** and choose this Git repository. The included Blueprint configures a **paid Starter** web service with a **1 GB persistent disk** mounted at `/var/data`. Review current Render pricing before confirming.
3. When asked for `ORANEO_AUTH_PASSWORD`, enter a strong unique password. The username defaults to `oraneo`. Both credentials are required together. Render exposes the web application only through HTTPS; browsers will request HTTP Basic credentials.
4. Deploy. Render builds React with Node.js, installs Python requirements, and runs `uvicorn ... --workers 1` on `$PORT`. Health is `/api/v1/health`. The React dashboard is at the service root `/`, with FastAPI at `/api/v1/*` and Swagger at `/docs`.
5. On the **first boot** only, the startup copies the bundled South African demonstration seed to `/var/data/warehouse.db`. All future ETL runs and report uploads use the persistent disk; a redeployment **does not overwrite it**.

### Render and SQLite limits

- The **free** web tier does not persist SQLite file updates and can sleep when idle, stopping scheduled ETL. For real, durable data and schedules, use the paid persistent-disk configuration in `render.yaml`. Never treat a free-tier SQLite deployment as reliable storage.
- Render disks mount to **a single instance**, so this application intentionally runs one Uvicorn worker. Do not scale to multiple instances or launch multiple independent schedulers against the same file. Persistent disk deployments can have brief downtime during updates.
- Scheduler jobs run only while the web service is awake. They are not a separate durable cloud task queue; long-running/critical production processing should use an external job runner and a managed database in a future architecture.
- ORANEO uses browser HTTP Basic authentication for an owner-operated dashboard, **not role-based multiuser accounts**. Use HTTPS and a strong password. For a public multiuser application, introduce a proper auth and role system before exposing uploaded business data.
- Render's separate cron jobs cannot directly access the web service's persistent disk. Do not configure a second cron process to write this SQLite database.

Render's policies: [persistent disks](https://render.com/docs/disks), [free instance limitations](https://render.com/docs/free), [deployments](https://render.com/docs/deploys).

## Configuration

Environment settings live in `backend/app/config.py`. All relative filesystem paths are rooted at the project directory rather than the shell's current folder.

| Variable | Default locally | Render Blueprint |
|---|---|---|
| `SALES_DB_PATH` | `data/warehouse.db` | `/var/data/warehouse.db` |
| `SALES_RAW_PATH` | `data/raw/sales_raw.csv` | bundled source CSV |
| `SALES_UPLOAD_DIR` | `data/uploads` | `/var/data/uploads` |
| `SALES_REPORT_DIR` | `data/reports` | `/var/data/reports` |
| `SALES_PROCESSED_DIR` | `data/processed` | `/var/data/processed` |
| `SALES_CURRENCY` | `ZAR` | `ZAR` |
| `ORANEO_SCHEDULER_ENABLED` | `true` | `true` |
| `ORANEO_SEED_ON_FIRST_BOOT` | `false` | `true` |
| `ORANEO_AUTH_USER` / `ORANEO_AUTH_PASSWORD` | not set (localhost only) | required credentials |
| `VITE_API_BASE_URL` | `/api/v1` | `/api/v1` |

Python reads environment variables from the actual process environment; it does **not** automatically parse `.env`. Use `.env.example` as a reference. Do not place passwords in Vite environment variables (those are embedded in the browser build).

## Troubleshooting the earlier HTTP 500

1. `cd` into **`oraneo`**, not the outer extracted folder. The correct database is `oraneo/data/warehouse.db` when viewing from the outer folder.
2. Run `python start.py` with your activated virtual environment. Confirm `/api/v1/health` returns status `ok` and `/api/v1/diagnostics` says `ready:true` with the expected sales count. The test fixture may start with zero rows by design.
3. Verify data using Python without installing the SQLite command-line tool:

   ```powershell
   python -c "import sqlite3; c=sqlite3.connect('data/warehouse.db'); print(c.execute('SELECT count(*) FROM fact_sales').fetchone())"
   ```

4. If a request still fails, inspect the **FastAPI terminal traceback** and the browser's Network tab. SQLite errors return a helpful 503 with a pointer to diagnostics; non-database Python errors appear in API logs. Do not delete or overwrite the working warehouse to guess at a fix.
5. If `npm install` fails, verify DNS/network connectivity to `registry.npmjs.org`, npm proxy settings and your Node version. The frontend cannot run without its packages.
6. For missing rendered styles check that `frontend/src/styles/pink.css` imports from `frontend/src/main.tsx`. Poppins is remotely loaded from Google Fonts.

## Backups and limitations

Back up the **entire SQLite file** while no ETL job is writing, preferably with `sqlite3.Connection.backup()` for an online backup. Also preserve `/var/data/uploads` and generated `/var/data/reports` if needed. Never manually run `.read sql/analytics.sql` against the wrong SQLite file; those are analytics `SELECT`s, not migrations.

**Validation completed in the preparation environment:** Python backend tests, in-process FastAPI endpoint tests, PDF text generation, CSS parsing, and a TypeScript/TSX syntax parse. Frontend npm install and browser build need to be run in a network-enabled environment (Render or local Windows). The source archive does not claim that those unrun checks passed.

## Project structure

`backend/app/` REST API, scheduler, insights and configuration; `src/` validated ETL, SQLite warehouse, reports and PDF generation; `frontend/src/` eight React screens and the Poppins-pink theme; `tests/` isolated Python tests; `data/raw/` South African synthetic input; `data/seed/` deployable baseline; `data/legacy/` original preserved sample; `render.yaml` and `Dockerfile` deployment definition; `start.py` concurrent development launcher.


# Verification code:
WTC-G3SP4PVK

