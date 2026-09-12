# CLAUDE.md

Follow **AGENTS.md** (repo root) — it holds the repo map, commands, data-pipeline gotchas, conventions, and definition of done. This file only adds Claude-specific working notes.

## Context

- **Full product spec:** `plans.md` is the complete working context for terrasim (modes, algorithms, demo script, visual identity §38–41, scientific-honesty rules §30, judge objections §31). Read it up front when starting work; re-read the visual/demo sections before UI work.
- **The money moment:** the demo *must* communicate "we didn't just simulate the disaster — we used the simulation to improve the city." Preserve the PLAN → SIMULATE → IMPROVE loop everywhere.

## Working notes

- **Log every change:** *always* update `implementation-log.md` in the same change as the code — it is the status ledger and it must never fall behind. Newest entry at the top, dated, written from what physically changed (backend/frontend/docs/data sections, concrete numbers), closing with a "Verified live" note that mirrors what you actually ran. If you touched code, tests, bundles, or demo copy, the log entry belongs to that same commit.
- **Voice:** scenario outputs are *estimated exposure layers*. In every UI string and API field, prefer *estimated / hypothetical / scenario-based / relative / candidate / exposure* and never *predicts / guaranteed / will collapse*. This framing is load-bearing, not decoration.
- **Aesthetic:** the app should read as a polished handcrafted pixel-art RPG (Pokemon FireRed-inspired chrome) over a real geospatial map, not as a generic dashboard and not as a toy. Pixel font for headers/icons only; readable body text.
- **Vibe-check before shipping:** open the running app and scrutinize it as a player, not an engineer. If anything looks "vibecoded" (default dev styling, inconsistent spacing, stock map look), it needs a pass before it counts as done.