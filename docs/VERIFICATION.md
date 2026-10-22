# ORANEO v3 verification log

Checks executed on 21 October 2026 against the source archive being delivered:

| Check | Observed result |
|---|---|
| `python -m pytest -q` | **44 passed** (including ETL, migrations, API, PDF, authentication, SPA fallback, database seeding) |
| Live Uvicorn at `127.0.0.1:8914` | Eight main endpoints returned **HTTP 200** |
| `/api/v1/diagnostics` live | Database `ready: true`, `sales_rows: 936` |
| TypeScript/TSX syntax parse (global TypeScript 5.8.3) | **18 files**, zero syntax diagnostics |
| Pink CSS via tinycss2 stylesheet parser | Parsed with **zero rule errors** |
| Render Blueprint via YAML parser | Valid YAML, Docker runtime with `/var/data` disk |
| Native-text PDF regenerated and extracted with pypdf | **4 pages**, text extraction successful, South African ZAR values |
| PDF first page rendered to PNG and inspected | Layout and pink line chart rendered correctly |

**Not executed:** `npm run test`, `npm run lint`, `npm run typecheck`, `npm run build`, interactive browser checks, and remote Render build/deployment. The package registry could not be resolved from this execution environment (`registry.npmjs.org`: DNS resolution failure), preventing installation of React, Vite and their dependencies. Passing a TSX syntax parse does **not** establish a successful React compilation. Run these checks locally after `npm install` or observe them in GitHub Actions/Render; do not claim a 100% end-to-end pass until they are green.

**No Render service was deployed** because deployment requires connecting the user's Git repository and Render account. `render.yaml`, Dockerfile, startup scripts, environment settings, and the persistently versioned seed DB are supplied for that step.
