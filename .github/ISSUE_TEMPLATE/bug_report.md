---
name: Bug report
about: A runnable-but-wrong demo output, crash, or broken flow
title: "[bug] "
labels: bug
assignees: ""
---

**Describe the bug**
What happened, and what should have happened instead.

**Steps to reproduce**
1. Pick city/mode …
2. …

**Expected vs actual**
- Expected:
- Actual:

**Environment**
- Browser + version:
- Deployed (render.com) or local (`run-dev.cmd`)?
- Commit / date:

**Context**
- Demo flow walked: existing-city simulate → assess, new-city plan → validate, or both?
- Is the honesty framing intact (outputs read *estimated / hypothetical*, nothing claims
  predicted damage)?
- Does `implementation-log.md` have an entry for this change? (A code change without one is not done.)

**Screenshots / console errors**
Paste any backend traceback or browser console error.

**Definition of done**
- [ ] `cd backend && uv run pytest` passes
- [ ] `cd frontend && npx tsc --noEmit -p tsconfig.app.json` passes
- [ ] `cd frontend && npm run build` passes
- [ ] `implementation-log.md` entry added (dated, grounded in what you verified)