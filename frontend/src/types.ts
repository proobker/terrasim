export type PointLngLat = { lng: number; lat: number };

export interface CityInfo {
  id: string;
  name: string;
  mode: "existing" | "new";
  status: string;
  center: [number, number];
  bounds: [number, number, number, number];
  zoom: number;
  grid: { ncols: number; nrows: number; res_deg: number };
  attribution: string[];
}

export type LayerKind = "buildings" | "roads" | "facilities";

export interface GeoFeature {
  type: "Feature";
  properties: Record<string, unknown> & { name?: string; type?: string; kind?: string; id?: number };
  geometry: {
    type: string;
    coordinates: number[] | number[][] | number[][][] | number[][][][];
  };
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: GeoFeature[];
}

export interface ScenarioAsset {
  kind: string;
  id?: string | null;
  name?: string | null;
  lng: number;
  lat: number;
}

export interface FloodScenario {
  city_id: string;
  source: PointLngLat;
  level_m: number;
  mode: "rise" | "absolute";
  assets?: ScenarioAsset[] | null;
}

export interface EarthquakeScenario {
  city_id: string;
  epicenter: PointLngLat;
  magnitude: number;
  depth_km: number;
  assets?: ScenarioAsset[] | null;
}

export type HazardKind = "flood" | "earthquake";

export interface FloodStats {
  cells_flooded: number;
  cell_resolution_m: number;
  water_surface_m: number;
  area_km2: number;
  percent_of_cells: number;
  max_depth_m?: number;
  mean_depth_m?: number;
  deep_area_km2?: number;
}

export interface ExposedAsset {
  kind: string;
  name?: string;
  id?: number;
  band?: string;
}

export interface AssetCounts {
  total: number;
  [key: string]: number;
}

export interface ExposureReport {
  assets: Record<string, AssetCounts>;
  affected?: ExposedAsset[];
  exposed?: ExposedAsset[];
}

export interface FloodResult {
  kind: "flood";
  scenario: FloodScenario;
  stats: FloodStats;
  overlay: FeatureCollection;
  dry: boolean;
  exposure?: ExposureReport;
}

export interface QuakeResult {
  kind: "earthquake";
  scenario: EarthquakeScenario;
  zones: FeatureCollection;
  bands: string[];
  area_km2: number;
  radii_km?: Record<string, number>;
  exposure: ExposureReport;
}

export type SimResult = FloodResult | QuakeResult;

export interface SuitabilityResult {
  layers: Record<"green" | "yellow" | "red", FeatureCollection>;
  legend: Record<string, string>;
  area_km2: Record<string, number>;
}

export type AssetType = "hospital" | "school" | "housing" | "fire_station" | "police" | "shelter";

export interface PlannedAsset {
  id: string;
  type: AssetType;
  lng: number;
  lat: number;
}