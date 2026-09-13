# Contributing to terrasim

> Building Resilient Areas for Climate & Emergencies — hackathon prototype. `plans.md` is the spec; read it (especially the honesty rules §30) before changing UI strings or API fields. `AGENTS.md` has the repo map and the definition of done.

## Setup

Follow **README.md** (backend `uv sync` + uvicorn; frontend `npm install` + `npm run dev`). Data bundles are committed, so the app runs without any network fetch.

## Making a change

1. Check the definition of done in `AGENTS.md` — every change ships with tests passing, typecheck + build passing, and the affected demo flow still walking.
2. Update `implementation-log.md` in the same change: newest entry at the top, dated, grounded in what you actually built and verified (concrete numbers, not prose). Write it from the diff, mirroring the existing entry format. A code change without its log entry is not done.
3. Backend physics goes in `backend/app/engine/` as pure functions (no I/O); route glue lives in `app/main.py`.
4. Frontend keeps the FireRed chrome (`src/index.css`, palette in plans.md §39). No "stock dashboard" styling.
5. Honesty framing is load-bearing: new UI strings and API fields say *estimated / hypothetical / scenario-based / candidate*, never *predicted damage / will collapse*.

## Tests

```bash
cd backend && uv run pytest        # 37 tests: engine (fast, no network) + API (bundle-backed)
cd frontend && npx tsc --noEmit -p tsconfig.app.json
cd frontend && npm run build
```

## Adding a city

1. `cd backend && uv run --group dev python ../scripts/fetch_data.py --city <id>`
2. Commit the resulting `data/bundles/<id>/` (never `data/fetch/`).
3. Read the Overpass gotchas in `AGENTS.md` before touching the fetch pipeline — the bbox order and mirror tolerance are load-bearing.

## Bugs and PRs

- A runnable but wrong demo output is a bug. Empty overlay, `dry` mishandled, or a half-painted layer are not acceptable fallbacks.
- Every PR updates `implementation-log.md` — land the entry with the code, not after the fact.
- Prefer one focused commit per fix with a `type: summary` subject (matching existing history).