import type { AssetType, GeoFeature, SimResult } from "./types";

// FireRed palette (plans.md §39): block silhouette colours sit muted so the
// hazard band pigments (risk red / teal flood) pop when a run tints a block.
const STONE = "#65746B";
const MOSS = "#4A5B52";
const EMERALD = "#287A45";
const TEAL = "#159A9C";
const CLAY = "#8A6A4B";
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

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string") {
    const m = v.match(/[\d.]+/);
    if (!m) return null;
    const x = parseFloat(m[0]);
    return Number.isFinite(x) ? x : null;
  }
  return null;
}

interface TypeDef {
  levels: number;
  color: string;
}

function typeDef(t: string): TypeDef {
  const k = String(t || "").toLowerCase();
  if (/(hospital|clinic|medical)/.test(k)) return { levels: 5, color: EMERALD };
  if (/(school|university|college|kinderga)/.test(k)) return { levels: 3, color: EMERALD };
  if (/(government|public|library|museum|office)/.test(k)) return { levels: 6, color: TEAL };
  if (/(supermarket|shop|retail|market|food|cafe|restaurant|mall)/.test(k))
    return { levels: 2, color: HIGHLIGHT };
  if (/(industrial|warehouse|garage|factory|storage)/.test(k)) return { levels: 6, color: STONE };
  if (/(apartment|flats|commercial|bank|hotel)/.test(k)) return { levels: 8, color: HIGHLIGHT };
  if (/(church|temple|mosque|place_of_worship)/.test(k)) return { levels: 6, color: CLAY };
  if (/(house|residential|hut|yes)/.test(k)) return { levels: 2, color: MOSS };
  return { levels: 2, color: MOSS };
}

// Estimated storey count. OSM "height" wins, then "building:levels", then the
// type table — always *estimated / illustrative*, never an actual measurement.
export function estimateHeight(props: Record<string, unknown>): number {
  const h = num(props.height);
  if (h !== null && h >= 2 && h <= 200) return Math.round(clamp(h, 3, 60) * 2) / 2;
  const lv = num(props["building:levels"]);
  if (lv !== null && lv >= 1) return Math.round(clamp(lv * 3.2, 3, 60) * 2) / 2;
  return Math.round(clamp(typeDef(String(props.type ?? "")).levels * 3.2, 3, 60) * 2) / 2;
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

// Centroid Point buildings from the bundle -> stylised polygon blocks with
// estimated heights. Frame of the whole visualisation: illustrative blocks,
// not measured footprints.
export function buildBlockFeatures(raw: GeoFeature[]): BlockFeature[] {
  return raw.map((f) => {
    const props = (f.properties ?? {}) as Record<string, unknown>;
    const coords = (f.geometry?.coordinates ?? []) as number[];
    const lng = coords[0] ?? 0;
    const lat = coords[1] ?? 0;
    const id = props.id;
    const seed = String(id ?? `${lng.toFixed(6)},${lat.toFixed(6)}`);
    const h = hash(seed);
    const sizeM = 10 + (h % 13); // 10..22 m — compact toy-city density
    const rotDeg = (h % 2) * 45;
    return {
      type: "Feature",
      properties: {
        ...props,
        id,
        height: estimateHeight(props),
        color: typeDef(String(props.type ?? "")).color,
      },
      geometry: { type: "Polygon", coordinates: squareCoord(lng, lat, sizeM, rotDeg) },
    } as BlockFeature;
  });
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