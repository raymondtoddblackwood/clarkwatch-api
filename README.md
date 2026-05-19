# clarkwatch-api

Read-only Railway service powering ClarkWatch widgets at `clark.dbnr.ai/clarkwatch/`.

## Purpose

Aggregates `clark_watch_details`, `clark_watch_summaries`, and `meditation_reports` from Supabase into widget-shaped JSON for the Clark Console. One service, one canonical filter, six widgets.

Phase 0 ships only `/health` and the canonical-filter library. Phase 1 adds `/snr/daily`. Remaining endpoints land in subsequent phases per the build spec.

## Source spec

`Agent Workspace DOE/directives/clark-console-clarkwatch-widgets-spec.md`

## Endpoints

| Endpoint | Phase | Purpose |
|---|---|---|
| `GET /health` | 0 | Liveness probe. Returns `{status, version, as_of}`. Open. |
| `GET /snr/daily?days=30` | 1 | Signal:Noise gauge — daily class counts. |
| `GET /cascade/health` | 2 | Cascade rollup health — pending. |
| `GET /agents/liveness` | 3 | Agent liveness matrix — pending. |
| `GET /agents/card/{surface}` | 4 | Pokemon card lifetime extension — pending. |
| `GET /meditation/backlog` | 5 | Contradiction backlog trendline — pending. |
| `GET /calendar/day-types` | 6 | Day-type compass — pending. |

## Auth

`X-ClarkWatch-Token: ${CLARKWATCH_API_SECRET}` on every endpoint except `/health`.

## CORS

Allowlist: `https://clark.dbnr.ai`, `https://dbnr.info`, `http://localhost:8000`.

## Env vars

| Var | Required | Purpose |
|---|---|---|
| `CLARKWATCH_API_SECRET` | yes | Shared bearer secret for /widgets endpoints |
| `SUPABASE_URL` | yes | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | Service-role key for read access |
| `CORS_ALLOWED_ORIGINS` | no | Comma-separated, defaults to console + dbnr.info |

## Local dev

```
pip install -r requirements.txt
export CLARKWATCH_API_SECRET=dev_secret
export SUPABASE_URL=https://xwpfdmdfvumnhmdafalm.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=...
uvicorn app.main:app --reload --port 8080
```

## Deploy

Push to `main` on `raymondtoddblackwood/clarkwatch-api`. Railway picks up the Dockerfile and deploys.
