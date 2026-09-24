---
name: Feature request
about: A new capability or improvement for the demo / platform
title: "[feat] "
labels: enhancement
assignees: ""
---

**Problem / opportunity**
What the demo needs and why. Tie it to the PLAN → SIMULATE → IMPROVE loop where possible.

**Proposed behavior**
Describe the user-facing behaviour, keeping the honesty framing (*estimated /
hypothetical / scenario-based*, never *predicted damage*).

**Design / implementation sketch (optional)**
- Backend: engine module (`app/engine/`, pure functions) vs route glue (`app/main.py`)
- Frontend: which panel / map layer / palette it touches
- Data: new bundle or new fetch-pipeline step?

**Demo impact**
Which section of the demo script (`plans.md` §44–47) this strengthens.

**Definition of done**
- [ ] `cd backend && uv run pytest` passes
- [ ] `cd frontend && npx tsc --noEmit -p tsconfig.app.json` passes
- [ ] `cd frontend && npm run build` passes
- [ ] Affected demo flow still walks per `plans.md` §44 (existing + new city)
- [ ] `implementation-log.md` entry added (dated, grounded in what you verified)