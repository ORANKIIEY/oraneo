# ORANEO v3 verification log

Checks executed on 26 October 2026 in this workspace.

| Check | Observed result |
|---|---|
| `python -m pytest -q` | **50 passed**, 1 warning (`StarletteDeprecationWarning` from FastAPI's `TestClient` import). Includes ETL, API, PDF, authentication, SPA fallback, and `test_persistent_database_is_seeded_once`. |
| Seed warehouse `data/seed/warehouse_seed.db` | Built from `data/raw/sales_raw.csv`. **1,020 input = 936 accepted + 64 rejected + 20 duplicates.** `fact_sales` has 936 rows. `export_status` is `complete`. No machine-specific export path is stored. |
| `npm ci --no-audit` (frontend) | Exit 0. Installed 338 packages from `frontend/package-lock.json`. |
| `npm run test` | **7 passed** (`src/pages/pages.test.tsx`). |
| `npm run lint` | Exit 0. **1 warning**, 0 errors: `Pipeline.tsx` `useEffect` missing dependency `notify` (`react-hooks/exhaustive-deps`). |
| `npm run typecheck` | Exit 0. |
| `npm run build` | Exit 0. Vite production build wrote `frontend/dist`. |

The seeding test starts the API with `ORANEO_SEED_ON_FIRST_BOOT=true`, checks the copied warehouse has orders, changes one city, starts again, and checks that second boot does not overwrite the change.

Docker UI stage copies `frontend/package.json` and `frontend/package-lock.json`, then runs `npm ci` so the image matches CI.

Python was 3.14.7 on this machine (the README supports 3.11–3.13). Node was v24.20.0. No Render service was deployed from this check; deployment still needs the user's Git repository and Render account.
