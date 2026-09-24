**What this PR does**

One focused change. Reference the issue: `Closes #<n>`.

**Checks (definition of done, AGENTS.md)**

- [ ] `cd backend && uv run pytest` passes
- [ ] `cd frontend && npx tsc --noEmit -p tsconfig.app.json` passes
- [ ] `cd frontend && npm run build` passes
- [ ] Affected demo flow (§44 existing + new city) still walks
- [ ] Honesty framing intact: anything new says *estimated / hypothetical /
      scenario-based / candidate* — never *predicted* / *guaranteed*
- [ ] `implementation-log.md` entry added (newest at top, dated, grounded in the diff)
- [ ] One focused commit with `type: summary` subject

**Screenshots / evidence**
If the change is visual or flow-based, paste before/after and the test results.