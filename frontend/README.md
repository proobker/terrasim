# terrasim frontend

Vite + React 19 + TypeScript dev client for the [terrasim](../README.md) demo.
Renders the map, 3D terrain and real OSM building footprints as estimated-height
3D blocks over a Pokemon FireRed-flavoured pixel-art UI — not a stock dashboard.

## Stack

- React 19 + TypeScript + Vite
- MapLibre GL JS (WebGL2 map engine)
- zustand (shared state)
- oxlint (linting)

## Run

```bash
npm install
npm run dev
```

Open `http://localhost:5173`. The backend must be running on
`http://127.0.0.1:8000` (override with `VITE_API_BASE`).

## Quality gates

```bash
npx tsc --noEmit -p tsconfig.app.json     # typecheck
npm run build                             # typecheck + production build
```

## Layout

```
src/
  App.tsx           mode switch, boot screen, toasts, facility chips
  MapView.tsx       MapLibre map + hazard/terrain layers; click-to-set source/epicenter; place/move/stamp assets; draw a flood channel
  SidePanel.tsx     Scenario Lab (existing) / Land Planning (new) controls
  ExposurePanel.tsx result stats + per-asset verdicts (flood → `affected`, quake → `exposed`)
  store.ts          zustand store (city/mode/hazard/params/source/result/placedAssets/drawn river/...)
  useSimulate.ts    runHazard / planAssets / useSuitability API hooks
  api.ts            endpoint list for the backend
  buildings3d.ts    real OSM footprints → 3D extrusions (estimated heights, band tinting)
  pixelIcons.ts     canvas-generated pixel sprites (atlasDefinitions + previewCanvas)
  index.css         full pixel/FireRed design system (palette in plans.md §39)
```

## Conventions

- Every measurement label reads "~N m est." — heights are estimates, never
  measurements.
- Band colours mark *scenario exposure*, never damage.
- FireRed chrome is a requirement, not a garnish.