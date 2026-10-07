import type { AssetType, SimResult } from "./types";

// Real city blocks (OSM footprints, estimated heights, stable silhouette tints)
// are cut into vector tiles and styled server-side in
// backend/app/engine/building_tiles.py. This module styles the planner's
// placed assets and maps a sim result to hazard bands.

// FireRed palette (plans.md §39): block silhouette colours sit muted so the
// hazard band pigments (risk red / teal flood) pop when a run tints a block.
const STONE = "#65746B";
const EMERALD = "#287A45";
const TEAL = "#159A9C";
const HIGHLIGHT = "#E6C66A";
export const SELECTED_COLOR = "#EFE6C9";

export interface BlockProperties {
  height: number;
  color: string;
  band?: string;
  id?: number | string;
  name?: string;
  type?: string;
  selected?: boolean;
  [key: string]: unknown;
}

export interface BlockFeature {
  type: "Feature";
  properties: BlockProperties;
  geometry: { type: "Polygon"; coordinates: number[][][] };
}

export interface PlacedBlockInput {
  id: string;
  type: AssetType;
  lng: number;
  lat: number;
  selected: boolean;
}

// FNV-1a — deterministic, so a block's footprint/colour never flickers
// between renders or restarts.
function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function corner(
  cLng: number,
  cLat: number,
  radiusM: number,
  angleRad: number,
): [number, number] {
  const mPerDegLat = 111320;
  const mPerDegLng = 111320 * Math.cos((cLat * Math.PI) / 180);
  return [
    cLng + (Math.cos(angleRad) * radiusM) / mPerDegLng,
    cLat + (Math.sin(angleRad) * radiusM) / mPerDegLat,
  ];
}

// Axis-aligned (or 45° toy-city twist) square footprint, side ≈ sizeM.
export function squareCoord(
  lng: number,
  lat: number,
  sizeM: number,
  rotDeg: number,
): number[][][] {
  const radiusM = (sizeM / 2) * Math.SQRT2;
  const base = (rotDeg * Math.PI) / 180 + Math.PI / 4;
  const pts = [0, 1, 2, 3].map((k) =>
    corner(lng, lat, radiusM, base + (k * Math.PI) / 2),
  );
  return [[...pts, pts[0]]];
}

// Attach the current hazard band to blocks whose key matches. Blocks that are
// not exposed keep their silhouette colour.
export function applyBands(
  blocks: BlockFeature[],
  bandByKey: Map<string, string>,
): BlockFeature[] {
  if (!bandByKey.size) return blocks;
  return blocks.map((b) => {
    const band = bandByKey.get(String(b.properties.id ?? ""));
    if (!band) return b;
    return { ...b, properties: { ...b.properties, band } };
  });
}

// Band keys from a sim result: quake exposes by intensity band, flood by
// affected ('flood'), keyed by the bundle/placement id.
export function bandsFromResult(result: SimResult | null): Map<string, string> {
  const m = new Map<string, string>();
  if (!result) return m;
  const entries =
    result.kind === "flood"
      ? (result.exposure?.affected ?? []).map((a) => [String(a.id ?? ""), a.band ?? "flood"] as const)
      : (result.exposure?.exposed ?? [])
          .filter((a) => a.band)
          .map((a) => [String(a.id ?? ""), a.band as string] as const);
  for (const [k, v] of entries) m.set(k, v);
  return m;
}

const ASSET_DEFS: Record<AssetType, { sizeM: number; height: number; color: string }> = {
  hospital: { sizeM: 34, height: 14, color: HIGHLIGHT },
  fire_station: { sizeM: 28, height: 10, color: "#E59B45" },
  school: { sizeM: 30, height: 11, color: EMERALD },
  police: { sizeM: 26, height: 10, color: TEAL },
  shelter: { sizeM: 32, height: 8, color: HIGHLIGHT },
  housing: { sizeM: 22, height: 8, color: STONE },
};

// Placed planning assets -> stylised blocks. Sizes/heights are illustrative
// footprints for the extended-area estimate overlay.
export function buildAssetBlocks(items: PlacedBlockInput[]): BlockFeature[] {
  return items.map((it) => {
    const def = ASSET_DEFS[it.type] ?? { sizeM: 24, height: 9, color: STONE };
    const rotDeg = (hash(it.id) % 4) * 45 + ((hash(it.id) >> 3) % 2) * 22.5;
    return {
      type: "Feature",
      properties: {
        id: it.id,
        type: it.type,
        name: it.type.replace(/_/g, " "),
        height: def.height,
        color: def.color,
        selected: it.selected,
      },
      geometry: { type: "Polygon", coordinates: squareCoord(it.lng, it.lat, def.sizeM, rotDeg) },
    } as BlockFeature;
  });
}