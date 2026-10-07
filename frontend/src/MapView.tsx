import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";

// maplibre v6 resolves its worker URL from import.meta.url, which a bundler
// rewrites so the sibling worker file is never served. Point it at the worker
// Vite emits/`?worker&url`-bundles before any Map is constructed.
maplibregl.setWorkerUrl(maplibreWorkerUrl);
import { api } from "./api";
import { applyBands, bandsFromResult, buildAssetBlocks } from "./buildings3d";
import { atlasDefinitions, iconForType } from "./pixelIcons";
import { padBounds, prefetch, tileUrls } from "./prefetch";
import { useStore } from "./store";
import type { FeatureCollection, GeoFeature, PointLngLat } from "./types";

// City buildings arrive as vector tiles cut by the backend
// (backend/app/engine/building_tiles.py): the browser only fetches the tiles
// in view instead of cloning and re-tiling ~362k footprints on every load.
const BUILDINGS = "ts-infra-buildings";
const BUILDINGS_SOURCE_LAYER = "buildings";
const buildingTilesUrl = (cityId: string) =>
  `${api.base}/api/cities/${cityId}/tiles/buildings/{z}/{x}/{y}.pbf`;

// Layer order, bottom -> top. Re-applied whenever a layer is added/removed.
const LAYER_ORDER = [
  "ts-sus-red",
  "ts-sus-yellow",
  "ts-sus-green",
  "ts-water",
  "ts-river-sel",
  "ts-river-flow",
  "ts-drawn-river",
  "ts-overlay",
  "ts-flood-shore",
  BUILDINGS,
  "ts-valley-rim",
  "ts-infra-roads",
  "ts-infra-facilities",
  "ts-exposed-dots",
  "ts-plan-3d",
  "ts-plan-assets",
  "ts-pulse",
  "ts-annos",
];

const QUIET_SRC = {
  type: "geojson",
  data: { type: "FeatureCollection", features: [] },
} as const;

function fc(
  features: ReadonlyArray<{
    type: "Feature";
    properties: Record<string, unknown>;
    geometry: unknown;
  }>,
): FeatureCollection {
  return { type: "FeatureCollection", features: features as FeatureCollection["features"] };
}

function webgl2Available(): boolean {
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    // Release the probe right away: Chrome caps live WebGL contexts (~16) and
    // evicts the *oldest* — every leaked probe (StrictMode, HMR remounts)
    // pushes the real map's context closer to being lost.
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    return !!gl;
  } catch {
    return false;
  }
}

// MapLibre composites each terrain tile into a cached render-to-texture
// (RTT). When fill-extrusion data arrives/asynchronously changes *after* that
// composite (network loads, band tints, moved assets), some tiles keep
// rendering the stale — flat — version until an interaction churns the cache
// (maplibre-gl#3001). Release the cached composites so the next frame
// re-draws extrusions on the live terrain.
function refreshTerrainRTT(map: maplibregl.Map) {
  try {
    if (!map.terrain) return;
    map.terrain.tileManager.releaseAllRTT();
    map.triggerRepaint();
  } catch {
    // terrain internals vary by maplibre version; best-effort refresh only
  }
}

// Several effects (bands, moved assets, city swap) want an RTT rebuild on the
// same frame — each naive rAF remounts the whole terrain (releaseAllRTT) and
// recomposites everything once, which during bursts stretches the draped
// raster across tiles mid-load. Coalesce to at most one release per frame.
let terrainRttFlight: number | null = null;

function scheduleTerrainRefresh(map: maplibregl.Map) {
  if (terrainRttFlight !== null) return;
  terrainRttFlight = requestAnimationFrame(() => {
    terrainRttFlight = null;
    refreshTerrainRTT(map);
  });
}

// Global SRTM-derived terrarium DEM (AWS Terrain Tiles, keyless). The mesh is
// rendered from a *global* source so it never falls off a coverage edge: the
// old city-only DEM 404'd past its padded box, maplibre dropped to a flat 0 m
// plane there, and the ~1300 m cliff read as white fogged walls and spikes.
// The flood/quake engines still run on the bundle DEM (same SRTM lineage).
const GLOBAL_DEM_TILES = [
  "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
];
// SRTM is ~30 m; terrarium z12 is ~34 m/px at Nepal's latitude, so z13-15 are
// upsampled copies of the same data. Capping here means one DEM tile covers a
// ~9 km square at any camera zoom — far fewer fetches while panning close in.
const DEM_MAXZOOM = 12;

const SATELLITE_TILES = [
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
];
// The coarse imagery underlay stops here: a handful of tiles covers the whole
// valley, so it is always loaded by the time the sharp tiles are still in flight.
// It is also the seam between two differently graded Esri mosaics — z<=11 is
// yellow-green (blue channel ~1/2 of z12's over the same ground) — so the sharp
// layer starts at z12 and the underlay is colour-matched to it, instead of the
// two meeting as a hard band mid-valley.
const SATELLITE_LO_MAXZOOM = 11;

function applyTerrain(map: maplibregl.Map, enabled: boolean) {
  if (!map.getSource("dem")) {
    map.addSource("dem", {
      type: "raster-dem",
      tiles: GLOBAL_DEM_TILES,
      tileSize: 256,
      maxzoom: DEM_MAXZOOM,
      encoding: "terrarium",
      attribution: "Terrain © Mapzen/AWS",
    });
  }
  if (enabled) {
    map.setTerrain({ source: "dem", exaggeration: 1.2 });
    // Google Earth-style atmosphere: deep blue zenith, pale horizon haze that
    // swallows distant ridges, fading out as the camera zooms in close.
    map.setSky({
      "sky-color": "#3f7fc4",
      "horizon-color": "#d6e6f2",
      "fog-color": "#c9dbe8",
      "fog-ground-blend": 0.6,
      "horizon-fog-blend": 0.6,
      "sky-horizon-blend": 0.7,
      "atmosphere-blend": [
        "interpolate",
        ["linear"],
        ["zoom"],
        0,
        1,
        10,
        1,
        14,
        0.4,
      ],
    });
  } else {
    map.setTerrain(null);
    map.setSky({
      "atmosphere-blend": 0,
      "sky-color": "#dcebf5",
      "horizon-color": "#ffffff",
      "fog-color": "#ffffff",
    });
  }
}

export default function MapView({
  onReady,
  onLoadProgress,
}: {
  onReady?: () => void;
  onLoadProgress?: (fraction: number, stage: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const initializedCity = useRef<string | null>(null);
  // The boot screen holds until the first city's tiles are preloaded.
  const readyFired = useRef(false);
  const prefetchAbort = useRef<AbortController | null>(null);
  const webgl2 = useRef<boolean>(webgl2Available());
  // maplibre v6 only allows style mutations after the style has loaded.
  const [mapLoaded, setMapLoaded] = useState(false);
  // Hover label over the voxel blocks (position + copy).
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  // City layers (roads/buildings/...) fetched but not yet drawn; shown as an
  // in-map chip so a half-built city never passes for a finished one.
  const [layersPending, setLayersPending] = useState(false);

  const city = useStore((s) => s.city);
  const mode = useStore((s) => s.mode);
  const hazard = useStore((s) => s.hazard);
  const source = useStore((s) => s.source);
  const selectedRiverId = useStore((s) => s.selectedRiverId);
  const result = useStore((s) => s.result);
  const suitability = useStore((s) => s.suitability);
  const placed = useStore((s) => s.placed);
  const pendingAsset = useStore((s) => s.pendingAsset);
  const selectedAssetId = useStore((s) => s.selectedAssetId);
  const drawingRiver = useStore((s) => s.drawingRiver);
  const drawnRiver = useStore((s) => s.drawnRiver);
  const showRoads = useStore((s) => s.showRoads);
  const showBuildings = useStore((s) => s.showBuildings);
  const showFacilities = useStore((s) => s.showFacilities);
  const showSuitability = useStore((s) => s.showSuitability);
  const terrain3d = useStore((s) => s.terrain3d);
  const showBlocky3d = useStore((s) => s.showBlocky3d);
  const showValleyRim = useStore((s) => s.showValleyRim);
  // OSM ids -> facility features, for tinting exposed assets after a run.
  const facilitiesRef = useRef<Map<string, GeoFeature>>(new Map());
  // Water-layer features keyed by OSM id, for drawing the selected river.
  const waterRef = useRef<Map<string, GeoFeature>>(new Map());
  // Building ids currently tinted through feature state.
  const bandedRef = useRef<Set<number>>(new Set());
  // Valley-rim line (dashed boundary of the sim basin), per city.
  const rimRef = useRef<FeatureCollection | null>(null);
  // Brush used to draw the quake pulse halo; kept in a ref so the rAF loop
  // doesn't re-subscribe on every pixel.
  const pulseRef = useRef<{ radius: number; color: string } | null>(null);

  const setSource = useStore((s) => s.setSource);
  const setFacilityDetail = useStore((s) => s.setFacilityDetail);
  const addPlaced = useStore((s) => s.addPlaced);
  const moveSelectedPlaced = useStore((s) => s.moveSelectedPlaced);
  const selectAsset = useStore((s) => s.selectAsset);
  const setPendingAsset = useStore((s) => s.setPendingAsset);
  const setStampGrid = useStore((s) => s.setStampGrid);
  const appendDrawPoint = useStore((s) => s.appendDrawPoint);
  const setError = useStore((s) => s.setError);

  // Live "rubber-band" preview while drawing a channel; committed points live
  // in the store so the panel can undo/clear them.
  const [riverPreview, setRiverPreview] = useState<PointLngLat | null>(null);

  // --- create map once -----------------------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (!webgl2.current) {
      // v6 is WebGL2-only; be honest instead of a silent blank canvas.
      onReady?.();
      setError(
        "Map can't start: WebGL2 is unavailable in this browser. Enable hardware acceleration, or use a recent Chrome/Edge/Firefox.",
      );
      return;
    }
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          satellite: {
            type: "raster",
            tiles: SATELLITE_TILES,
            tileSize: 256,
            attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
            minzoom: SATELLITE_LO_MAXZOOM + 1,
            maxzoom: 19,
          },
          "satellite-lo": {
            type: "raster",
            tiles: SATELLITE_TILES,
            tileSize: 256,
            maxzoom: SATELLITE_LO_MAXZOOM,
          },
        },
        layers: [
          // Under terrain, a draped tile with no imagery yet renders
          // transparent: the page shows through and the neighbours' skirts
          // read as stretched curtains. These two layers sit under the sharp
          // imagery so a still-loading tile is blurry ground, never a hole.
          {
            id: "ts-ground",
            type: "background",
            paint: { "background-color": "#6b6a4c" },
          },
          {
            id: "ts-satellite-lo",
            type: "raster",
            source: "satellite-lo",
            // Least-squares fit of z11 tile colours to their z12 children
            // (as drawn by ts-satellite) over 15 tiles around Kathmandu: RMS
            // gap 35 -> 15 /255. Desaturating lifts the starved blue channel.
            paint: {
              "raster-saturation": -0.2,
              "raster-contrast": -0.06,
              "raster-brightness-min": 0.08,
              "raster-fade-duration": 0,
            },
          },
          {
            id: "ts-satellite",
            type: "raster",
            source: "satellite",
            // Google Earth-style ground: real imagery draped over the global
            // DEM. A light contrast/saturation lift keeps the hazy Himalayan
            // imagery from reading washed out under the sky fog.
            paint: {
              "raster-saturation": 0.1,
              "raster-contrast": 0.08,
              // Terrain composites the base map into an RTT; the stock fade
              // causes the raster to shimmer to white at every layer tile as
              // it loads in, which looks like stretched translucent faces over
              // the DEM. Snap to fully opaque once a tile is ready.
              "raster-fade-duration": 0,
            },
          },
        ],
      },
      center: [85.34, 27.7],
      zoom: 12,
      pitch: 55,
      maxPitch: 75,
      attributionControl: false,
      canvasContextAttributes: { antialias: true },
    });

    // Bottom-right sits under the Scenario Lab panel; keep the (required)
    // imagery credit visible beside the zoom buttons instead.
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "bottom-left",
    );
    map.addControl(
      new maplibregl.AttributionControl({ compact: false }),
      "bottom-left",
    );

    // GeoJSON setData parses in a worker, so a refresh scheduled right after it
    // can land before the new features exist and leave the draped overlay
    // missing until the camera moves. Recompose once each overlay source has
    // actually re-tiled its new data (camera-driven tile loads don't count).
    let refreshOnIdle = false;
    map.on("sourcedata", (e) => {
      if (
        e.sourceId?.startsWith("ts-") &&
        e.sourceDataType === "content" &&
        !refreshOnIdle
      ) {
        refreshOnIdle = true;
        map.once("idle", () => {
          refreshOnIdle = false;
          scheduleTerrainRefresh(map);
        });
      }
    });

    // Surface fatal map errors instead of a silent blank canvas. Tile-level
    // failures (e.g. a slow tile server) are warnings, not toasts. They carry
    // `tile`/`sourceId`; checking isStyleLoaded() alone isn't enough, since it
    // stays false while any tile is in flight, so a single tile that fails
    // during the first load (API on Render still cold-starting) would count
    // as fatal.
    map.on("error", (e) => {
      const ev = e as unknown as {
        error?: { message?: string };
        message?: unknown;
        tile?: unknown;
        sourceId?: string;
      };
      const msg = ev.error?.message ?? (typeof ev.message === "string" ? ev.message : String(e));
      const tileLevel = ev.tile !== undefined || ev.sourceId !== undefined;
      if (!tileLevel && !map.isStyleLoaded()) {
        setError(`Map failed to start: ${msg}`);
      } else {
        console.warn("[terrasim map]", msg);
      }
    });

    // On WebGL context loss maplibre destroys the style (map.style = null) and
    // re-applies a serialized copy on restore. Pause every style-touching
    // effect meanwhile — one setLayoutProperty on the dead style would throw
    // and blank the whole app.
    map.on("webglcontextlost", () => setMapLoaded(false));
    map.on("webglcontextrestored", () => {
      if (map.isStyleLoaded()) setMapLoaded(true);
      else map.once("style.load", () => setMapLoaded(true));
    });

    // Style mutations (images/sources/layers) must wait for the style to load —
    // maplibre throws "Style is not done loading" otherwise.
    map.once("load", () => {
      if (mapRef.current !== map) return;
      const atlas = atlasDefinitions();
      for (const [name, image] of Object.entries(atlas)) {
        const imageData = new ImageData(
          new Uint8ClampedArray(image.data),
          image.width,
          image.height,
        );
        map.addImage(name, imageData);
      }

      // static (empty) sources
      for (const id of [
        "ts-sus-green",
        "ts-sus-yellow",
        "ts-sus-red",
        "ts-water",
        "ts-river-sel",
        "ts-river-flow",
        "ts-drawn-river",
        "ts-overlay",
      ]) {
        map.addSource(id, QUIET_SRC as never);
      }
      // Tile URL is set per city (setTiles). The backend serves z13-15 — below
      // that a block is a sub-pixel speck — and maplibre overscales past z15.
      // Features carry their OSM id, so a sim run tints blocks through
      // feature state rather than re-sending any geometry.
      map.addSource(BUILDINGS, {
        type: "vector",
        tiles: [],
        minzoom: 13,
        maxzoom: 15,
      });
      map.addSource("ts-infra-roads", QUIET_SRC as never);
      map.addSource("ts-infra-facilities", QUIET_SRC as never);
      map.addSource("ts-plan-assets", QUIET_SRC as never);
      map.addSource("ts-plan-3d", QUIET_SRC as never);
      map.addSource("ts-valley-rim", QUIET_SRC as never);
      map.addSource("ts-annos", QUIET_SRC as never);
      map.addSource("ts-flood-shore", QUIET_SRC as never);
      map.addSource("ts-exposed", QUIET_SRC as never);
      map.addSource("ts-pulse", QUIET_SRC as never);

      map.addLayer({
        id: "ts-sus-green",
        type: "fill",
        source: "ts-sus-green",
        paint: { "fill-color": "#55B86A", "fill-opacity": 0.18 },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-sus-yellow",
        type: "fill",
        source: "ts-sus-yellow",
        paint: { "fill-color": "#E59B45", "fill-opacity": 0.32 },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-sus-red",
        type: "fill",
        source: "ts-sus-red",
        paint: { "fill-color": "#E34B4B", "fill-opacity": 0.38 },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-water",
        type: "line",
        source: "ts-water",
        paint: {
          "line-color": "#2E8DA0",
          "line-width": 2.4,
          "line-opacity": 0.55,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-river-sel",
        type: "line",
        source: "ts-river-sel",
        paint: {
          "line-color": "#6FE3F0",
          "line-width": 5,
          "line-opacity": 0.95,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-river-flow",
        type: "symbol",
        source: "ts-river-flow",
        layout: {
          "icon-image": "ts-flow",
          "icon-size": 0.75,
          "symbol-placement": "line",
          "symbol-spacing": 150,
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": false,
          visibility: "none",
        },
      });
      map.addLayer({
        id: "ts-drawn-river",
        type: "line",
        source: "ts-drawn-river",
        paint: {
          "line-color": "#E6C66A",
          "line-width": 5,
          "line-opacity": 0.9,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-overlay",
        type: "fill",
        source: "ts-overlay",
        paint: {
          "fill-color": [
            "match",
            ["get", "class"],
            "high",
            "#E34B4B",
            "medium_high",
            "#E59B45",
            "medium",
            "#E6C66A",
            "low",
            "#159A9C",
            "flood",
            "#43C7D8",
            "flood-deep",
            "#1E7A99",
            "#43C7D8",
          ],
          // Quake bands sit over satellite imagery now; 0.34 let the tan
          // valley floor swallow the medium/medium-high rings.
          "fill-opacity": ["match", ["get", "class"], "flood-deep", 0.7, "flood", 0.55, 0.46],
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-flood-shore",
        type: "line",
        source: "ts-flood-shore",
        paint: {
          "line-color": "#9BE8F2",
          "line-width": 2.2,
          "line-opacity": 0.95,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: BUILDINGS,
        type: "fill-extrusion",
        source: BUILDINGS,
        "source-layer": BUILDINGS_SOURCE_LAYER,
        paint: {
          // A hazard band (feature state, from a sim run) tints the whole
          // block; silent blocks keep their silhouette colour.
          "fill-extrusion-color": [
            "match",
            ["coalesce", ["feature-state", "band"], ""],
            "flood",
            "#43C7D8",
            "high",
            "#E34B4B",
            "medium_high",
            "#E59B45",
            "medium",
            "#E6C66A",
            "low",
            "#159A9C",
            ["get", "color"],
          ],
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-base": 0,
          "fill-extrusion-opacity": 0.92,
          "fill-extrusion-vertical-gradient": true,
        },
        layout: { visibility: "visible" },
      });
      map.addLayer({
        id: "ts-valley-rim",
        type: "line",
        source: "ts-valley-rim",
        paint: {
          "line-color": "#159A9C",
          "line-width": 2.2,
          "line-opacity": 0.8,
          "line-dasharray": [2.5, 1.5],
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-infra-roads",
        type: "line",
        source: "ts-infra-roads",
        paint: {
          "line-color": "#d9b957",
          "line-width": 1.3,
          "line-opacity": 0.85,
        },
      });
      map.addLayer({
        id: "ts-infra-facilities",
        type: "symbol",
        source: "ts-infra-facilities",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-size": 0.55,
          "icon-allow-overlap": true,
        },
      });
      map.addLayer({
        id: "ts-plan-3d",
        type: "fill-extrusion",
        source: "ts-plan-3d",
        paint: {
          "fill-extrusion-color": [
            "match",
            ["get", "band"],
            "flood",
            "#43C7D8",
            "high",
            "#E34B4B",
            "medium_high",
            "#E59B45",
            "medium",
            "#E6C66A",
            "low",
            "#159A9C",
            ["case", ["get", "selected"], "#EFE6C9", ["get", "color"]],
          ],
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-base": 0,
          "fill-extrusion-opacity": 0.95,
          "fill-extrusion-vertical-gradient": true,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-plan-assets",
        type: "symbol",
        source: "ts-plan-assets",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-size": ["case", ["get", "selected"], 1.5, 0.9],
          "icon-allow-overlap": true,
        },
      });
      map.addLayer({
        id: "ts-exposed-dots",
        type: "circle",
        source: "ts-exposed",
        paint: {
          "circle-radius": 3.2,
          "circle-color": [
            "match",
            ["get", "class"],
            "high",
            "#E34B4B",
            "medium_high",
            "#E59B45",
            "medium",
            "#E6C66A",
            "low",
            "#159A9C",
            "flood",
            "#43C7D8",
            "#FFFFFF",
          ],
          "circle-stroke-color": "#221F16",
          "circle-stroke-width": 1.2,
          "circle-opacity": 0.9,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-pulse",
        type: "circle",
        source: "ts-pulse",
        paint: {
          "circle-radius": 4,
          "circle-color": "#FFD9A8",
          "circle-stroke-color": "#E34B4B",
          "circle-stroke-width": 1.6,
          "circle-opacity": 0.9,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "ts-annos",
        type: "symbol",
        source: "ts-annos",
        layout: {
          "icon-image": ["get", "icon"],
          "icon-size": 0.9,
          "icon-allow-overlap": true,
        },
      });

      setMapLoaded(true);
    });

    // --- interactions -------------------------------------------------------
    map.on("click", (e) => {
      const lng = e.lngLat.lng;
      const lat = e.lngLat.lat;
      const s = useStore.getState();

      if (s.mode === "new") {
        if (s.drawingRiver) {
          appendDrawPoint({ lng, lat });
          return;
        }
        if (s.stampGrid && s.pendingAsset) {
          const n = s.stampGrid;
          const spacingM = 60;
          const mPerDegLat = 111320;
          const mPerDegLng = 111320 * Math.cos((lat * Math.PI) / 180);
          const base = Date.now();
          const off = (n - 1) / 2;
          for (let i = 0; i < n; i++) {
            for (let j = 0; j < n; j++) {
              addPlaced({
                id: `plan-${base}-${i}-${j}`,
                type: s.pendingAsset,
                lng: lng + ((i - off) * spacingM) / mPerDegLng,
                lat: lat + ((j - off) * spacingM) / mPerDegLat,
              });
            }
          }
          setStampGrid(null);
          return;
        }
        if (s.pickingOrigin) {
          s.setSource(lng, lat);
          s.setPickingOrigin(false);
          return;
        }
        if (s.pendingAsset) {
          const id = `plan-${Date.now()}`;
          addPlaced({ id, type: s.pendingAsset, lng, lat });
          setPendingAsset(null);
          selectAsset(id);
          return;
        }
        if (s.selectedAssetId) {
          moveSelectedPlaced(lng, lat);
          return;
        }
        return;
      }
      // existing mode: drop flood source / quake epicenter
      setSource(lng, lat);
    });

    // Rubber-band preview of the channel being drawn.
    map.on("mousemove", (e) => {
      const s = useStore.getState();
      if (s.mode === "new" && s.drawingRiver) {
        setRiverPreview({ lng: e.lngLat.lng, lat: e.lngLat.lat });
      } else if (s.mode !== "new" || !s.drawingRiver) {
        setRiverPreview((p) => (p ? null : p));
      }
    });
    map.getCanvas().addEventListener("mouseleave", () => setRiverPreview(null));

    map.on("click", "ts-infra-facilities", (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const props = f.properties ?? {};
      setFacilityDetail({
        name: (props.name as string) ?? "",
        type: (props.type as string) ?? "",
      });
    });

    map.on("mousemove", "ts-infra-facilities", (e) => {
      map.getCanvas().style.cursor = e.features?.length ? "pointer" : "";
    });
    map.on("mouseleave", "ts-infra-facilities", () => {
        map.getCanvas().style.cursor = "";
      });

    // --- voxel block hover labels -------------------------------------------
    const tipFrom = (
      e: maplibregl.MapLayerMouseEvent,
      f: maplibregl.MapGeoJSONFeature | undefined,
    ) => {
      const width = map.getCanvas().clientWidth;
      const x = Math.min(
        Math.max(e.point.x + 14, 8),
        width - 230,
      );
      const y = e.point.y + 16;
      if (!f) {
        setTip(null);
        map.getCanvas().style.cursor = "";
        return;
      }
      map.getCanvas().style.cursor = "pointer";
      const p = (f.properties ?? {}) as Record<string, unknown>;
      // City blocks carry their band in feature state, planned blocks in props.
      const band = (f.state?.band ?? p.band) as string | undefined;
      const tag = band
        ? band === "flood"
          ? "estimated flooded"
          : `stylized ${band} band`
        : "";
      const height = Math.round(Number(p.height) || 0);
      setTip({
        x,
        y,
        text:
          `${String(p.name ?? "Building")} · ~${height} m est.` +
          (tag ? ` · ${tag}` : ""),
      });
    };
    map.on("mousemove", BUILDINGS, (e) => tipFrom(e, e.features?.[0]));
    map.on("mouseleave", BUILDINGS, (e) => tipFrom(e, undefined));
    map.on("mousemove", "ts-plan-3d", (e) => tipFrom(e, e.features?.[0]));
    map.on("mouseleave", "ts-plan-3d", (e) => tipFrom(e, undefined));

    mapRef.current = map;
    // Dev-only handle so browser smoke tests can drive the camera.
    if (import.meta.env.DEV) {
      (window as unknown as { __terrasimMap?: maplibregl.Map }).__terrasimMap = map;
    }
    return () => {
      prefetchAbort.current?.abort();
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- fit to city & load the infra layers once per city --------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !city || !mapLoaded) return;
    if (initializedCity.current === city.id) return;
    initializedCity.current = city.id;

    const target =
      city.hazard_bounds ?? (city.bounds as [number, number, number, number]);
    // The Scenario Lab panel floats over the right of the map; keep the fitted
    // valley clear of it instead of framing the city underneath the panel.
    const panel = document.querySelector(".side-panel")?.getBoundingClientRect();
    const mapRect = map.getContainer().getBoundingClientRect();
    // Capped so a narrow (phone) layout can't pad the fit into an empty box.
    const panelCover = panel
      ? Math.min(mapRect.width * 0.45, Math.max(0, mapRect.right - panel.left))
      : 0;
    map.fitBounds(
      [
        [target[0], target[1]],
        [target[2], target[3]],
      ],
      {
        padding: { top: 60, bottom: 60, left: 60, right: panelCover + 40 },
        duration: 600,
      },
    );
    // The fitBounds camera sweep churns terrain RTT caches unevenly; recompose
    // everything once it settles so no flat tile lingers at rest.
    map.once("moveend", () => scheduleTerrainRefresh(map));

    applyTerrain(map, useStore.getState().terrain3d);

    // Forced preload. Core = the coarse DEM + coarse imagery underlay around
    // the valley: with it cached, any pan/tilt has *something* to drape (no
    // holes), so the boot screen waits on it (~90 tiles for Kathmandu).
    // Detail = sharp DEM and z12-14 imagery, streamed in after the reveal.
    prefetchAbort.current?.abort();
    const abort = new AbortController();
    prefetchAbort.current = abort;
    // Underlay imagery first: it is what keeps a pan from showing holes, and
    // Esri answers in ~100 ms where S3 DEM tiles take 1-4 s.
    const core = [
      ...tileUrls({
        template: SATELLITE_TILES[0],
        bounds: padBounds(target, 1),
        minzoom: 8,
        maxzoom: SATELLITE_LO_MAXZOOM,
      }),
      ...tileUrls({
        template: GLOBAL_DEM_TILES[0],
        bounds: padBounds(target, 0.5),
        minzoom: 8,
        maxzoom: DEM_MAXZOOM - 1,
      }),
    ];
    const detail = [
      ...tileUrls({
        template: GLOBAL_DEM_TILES[0],
        bounds: padBounds(target, 0.5),
        minzoom: DEM_MAXZOOM,
        maxzoom: DEM_MAXZOOM,
      }),
      // z12-13 is the sharp fallback the live imagery shows while z15+ tiles
      // stream in; past this ring the fallback drops to the blurry z11 underlay.
      ...tileUrls({
        template: SATELLITE_TILES[0],
        bounds: padBounds(target, 0.5),
        minzoom: SATELLITE_LO_MAXZOOM + 1,
        maxzoom: 13,
      }),
      ...tileUrls({ template: SATELLITE_TILES[0], bounds: target, minzoom: 14, maxzoom: 14 }),
    ];
    const firstCity = !readyFired.current;
    const timeout = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
    // Boot progress only ever moves forward, whichever stage lands first.
    let shown = 0;
    const report = (fraction: number, stage: string) => {
      if (!firstCity || fraction <= shown) return;
      shown = fraction;
      onLoadProgress?.(fraction, stage);
    };
    const corePrefetch = prefetch(core, {
      signal: abort.signal,
      onProgress: (f) => report(f * 0.45, "terrain & imagery"),
    });
    void corePrefetch.then(() => prefetch(detail, { signal: abort.signal, concurrency: 4 }));
    setLayersPending(true);

    // Buildings: point the tile source at this city; tiles stream per view.
    (map.getSource(BUILDINGS) as maplibregl.VectorTileSource | undefined)?.setTiles([
      buildingTilesUrl(city.id),
    ]);

    const layersLoaded = Promise.all([
      api.layer(city.id, "rim").then((data) => {
        rimRef.current = data && data.features.length ? data : null;
        const source = map.getSource("ts-valley-rim") as
          | maplibregl.GeoJSONSource
          | undefined;
        source?.setData(rimRef.current ?? fc([]));
        useStore.getState().setRimAvailable(Boolean(rimRef.current));
        map.setLayoutProperty(
          "ts-valley-rim",
          "visibility",
          rimRef.current && useStore.getState().showValleyRim
            ? "visible"
            : "none",
        );
      }),
      api.layer(city.id, "roads").then((data) => {
        const source = map.getSource(
          "ts-infra-roads",
        ) as maplibregl.GeoJSONSource;
        source?.setData(data ?? fc([]));
      }),
      api.layer(city.id, "facilities").then((data) => {
        const features = (data?.features ?? []).map((f) => ({
          ...f,
          properties: {
            ...f.properties,
            icon: iconForType((f.properties.type as string) ?? ""),
          },
        }));
        facilitiesRef.current = new Map(
          features.map((f) => [String(f.properties.id ?? ""), f]),
        );
        const source = map.getSource(
          "ts-infra-facilities",
        ) as maplibregl.GeoJSONSource;
        source?.setData(fc(features));
      }),
      api.layer(city.id, "water").then((data) => {
        const features = data?.features ?? [];
        waterRef.current = new Map(
          features.map((f) => [String(f.properties.id ?? ""), f]),
        );
        const source = map.getSource("ts-water") as maplibregl.GeoJSONSource;
        source?.setData(fc(features));
        map.setLayoutProperty(
          "ts-water",
          "visibility",
          features.length ? "visible" : "none",
        );
      }),
    ]);
    void corePrefetch.then(() => report(0.5, "city layers"));
    // Drawn = the worker has tiled the new data and the frame has settled;
    // for Kathmandu's 362k footprints that is most of the wait.
    const layersDrawn = layersLoaded
      .then(() => {
        report(0.8, "building the city");
        scheduleTerrainRefresh(map);
        return new Promise<void>((r) => {
          requestAnimationFrame(() => map.once("idle", () => r()));
        });
      })
      .catch((err: unknown) => setError(String(err)))
      .finally(() => {
        if (initializedCity.current === city.id) setLayersPending(false);
      });
    if (firstCity) {
      // Reveal a finished city: imagery cached, layers drawn. Capped so a slow
      // network still gets in; the in-map chip covers whatever is left.
      void Promise.race([Promise.all([corePrefetch, layersDrawn]), timeout(20000)]).then(() => {
        readyFired.current = true;
        onLoadProgress?.(1, "ready");
        onReady?.();
      });
    }
    // onReady/onLoadProgress are inline callbacks; the city guard above makes
    // this run once per city regardless.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [city, setError, mapLoaded]);

  // --- selected river highlight + flow direction (flood origin by river) -----
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const selSource = map.getSource("ts-river-sel") as
      maplibregl.GeoJSONSource | undefined;
    const flowSource = map.getSource("ts-river-flow") as
      maplibregl.GeoJSONSource | undefined;
    if (!selSource || !flowSource) return;
    const highlight =
      hazard === "flood" && selectedRiverId && waterRef.current.has(selectedRiverId)
        ? fc([waterRef.current.get(selectedRiverId)!])
        : fc([]);
    selSource.setData(highlight);
    flowSource.setData(highlight);
    const visible = highlight.features.length ? "visible" : "none";
    map.setLayoutProperty("ts-river-sel", "visibility", visible);
    map.setLayoutProperty("ts-river-flow", "visibility", visible);
  }, [selectedRiverId, hazard, mapLoaded]);

  // --- drawn river channel (New City hypothetical flood origin) --------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const src = map.getSource("ts-drawn-river") as
      | maplibregl.GeoJSONSource
      | undefined;
    if (!src) return;
    const path = drawnRiver?.path ?? [];
    const features: GeoFeature[] = [];
    if (path.length >= 2) {
      features.push({
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: path.map((p) => [p.lng, p.lat]),
        },
      });
    }
    if (mode === "new" && drawingRiver && riverPreview && path.length >= 1) {
      features.push({
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: [
            [path[path.length - 1].lng, path[path.length - 1].lat],
            [riverPreview.lng, riverPreview.lat],
          ],
        },
      });
    }
    src.setData(fc(features));
    map.setLayoutProperty(
      "ts-drawn-river",
      "visibility",
      features.length ? "visible" : "none",
    );
    try {
      map.moveLayer("ts-drawn-river");
    } catch {
      // layer ordering is best-effort during load
    }
  }, [drawnRiver, drawingRiver, riverPreview, mode, mapLoaded]);

  // --- infrastructure toggles ------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const setVis = (id: string, on: boolean) =>
      map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    setVis(BUILDINGS, showBuildings && showBlocky3d && mode === "existing");
    setVis("ts-infra-roads", showRoads && mode === "existing");
    setVis("ts-infra-facilities", showFacilities && mode === "existing");
  }, [showRoads, showBuildings, showFacilities, showBlocky3d, mode, mapLoaded]);

  // --- valley rim outline ----------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const on =
      showValleyRim && Boolean(rimRef.current && rimRef.current.features.length);
    map.setLayoutProperty("ts-valley-rim", "visibility", on ? "visible" : "none");
  }, [showValleyRim, mapLoaded]);

  // --- terrain elevation ------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded || !city) return;
    applyTerrain(map, terrain3d);
    if (terrain3d) scheduleTerrainRefresh(map);
  }, [terrain3d, city, mapLoaded]);

  // --- suitability overlay ---------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const setData = (id: string, data?: FeatureCollection | null) => {
      (map.getSource(id) as maplibregl.GeoJSONSource | undefined)?.setData(
        data ?? { type: "FeatureCollection", features: [] },
      );
    };
    setData(
      "ts-sus-red",
      mode === "new" && showSuitability ? suitability?.layers.red : null,
    );
    setData(
      "ts-sus-yellow",
      mode === "new" && showSuitability ? suitability?.layers.yellow : null,
    );
    setData(
      "ts-sus-green",
      mode === "new" && showSuitability ? suitability?.layers.green : null,
    );
    const setVis = (id: string, on: boolean) =>
      map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    setVis(
      "ts-sus-red",
      Boolean(mode === "new" && showSuitability && suitability),
    );
    setVis(
      "ts-sus-yellow",
      Boolean(mode === "new" && showSuitability && suitability),
    );
    setVis(
      "ts-sus-green",
      Boolean(mode === "new" && showSuitability && suitability),
    );
  }, [suitability, mode, showSuitability, mapLoaded]);

  // --- hazard result overlay -------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const overlay = map.getSource("ts-overlay") as
      maplibregl.GeoJSONSource | undefined;
    const shore = map.getSource("ts-flood-shore") as
      maplibregl.GeoJSONSource | undefined;
    const exposed = map.getSource("ts-exposed") as
      maplibregl.GeoJSONSource | undefined;
    const pulse = map.getSource("ts-pulse") as
      maplibregl.GeoJSONSource | undefined;

    let data: FeatureCollection = fc([]);
    let shoreData: FeatureCollection = fc([]);
    let exposedData: FeatureCollection = fc([]);
    let pulseData: FeatureCollection = fc([]);

    if (result?.kind === "flood" && !result.dry) {
      data = result.overlay;
      shoreData = fc(
        result.overlay.features.filter(
          (f) => f.properties.class === "flood",
        ),
      );
      const exposed = result.exposure?.affected ?? [];
      exposedData = fc(
        exposed
          .map((e): GeoFeature | null => {
            const g = facilitiesRef.current.get(String(e.id ?? ""));
            if (!g) return null;
            return {
              ...g,
              properties: { ...g.properties, class: e.band ?? "flood" },
            } as GeoFeature;
          })
          .filter((f): f is GeoFeature => Boolean(f)),
      );
    }

    if (result?.kind === "earthquake") {
      data = result.zones;
      const exposed = result.exposure?.exposed ?? [];
      exposedData = fc(
        exposed
          .map((e): GeoFeature | null => {
            const g = facilitiesRef.current.get(String(e.id ?? ""));
            if (!g) return null;
            return {
              ...g,
              properties: { ...g.properties, class: e.band ?? "medium" },
            } as GeoFeature;
          })
          .filter((f): f is GeoFeature => Boolean(f)),
      );
      const s = useStore.getState().source;
      if (s) {
        pulseRef.current = { radius: 4, color: "#E34B4B" };
        pulseData = fc([
          {
            type: "Feature",
            properties: { class: "high" },
            geometry: { type: "Point", coordinates: [s.lng, s.lat] },
          },
        ]);
      }
    }

    overlay?.setData(data);
    map.setLayoutProperty(
      "ts-overlay",
      "visibility",
      data.features.length ? "visible" : "none",
    );
    shore?.setData(shoreData);
    map.setLayoutProperty(
      "ts-flood-shore",
      "visibility",
      shoreData.features.length ? "visible" : "none",
    );
    exposed?.setData(exposedData);
    map.setLayoutProperty(
      "ts-exposed-dots",
      "visibility",
      exposedData.features.length ? "visible" : "none",
    );
    pulse?.setData(pulseData);
    map.setLayoutProperty(
      "ts-pulse",
      "visibility",
      pulseData.features.length ? "visible" : "none",
    );

    // Tint exposed city blocks through feature state: a repaint, not a
    // re-upload + re-tile of every footprint (which froze the page ~5 s and
    // blanked the city while it re-tiled).
    // Tile features carry the numeric OSM id; other keys can't match a block.
    const banded = new Set<number>();
    for (const [key, band] of bandsFromResult(result)) {
      const id = Number(key);
      if (!Number.isSafeInteger(id) || id < 0) continue;
      map.setFeatureState({ source: BUILDINGS, sourceLayer: BUILDINGS_SOURCE_LAYER, id }, { band });
      banded.add(id);
    }
    for (const id of bandedRef.current) {
      if (!banded.has(id)) {
        map.removeFeatureState({ source: BUILDINGS, sourceLayer: BUILDINGS_SOURCE_LAYER, id }, "band");
      }
    }
    bandedRef.current = banded;
    scheduleTerrainRefresh(map);
  }, [result, mapLoaded]);

  // --- annotations (flood source / epicenter) --------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const annoSource = map.getSource("ts-annos") as
      maplibregl.GeoJSONSource | undefined;
    // A selected river or drawn channel is drawn as its own highlight; a point
    // marker would only be a fallback origin in that case.
    if (
      !source ||
      !annoSource ||
      (hazard === "flood" && (selectedRiverId || (drawnRiver && drawnRiver.path.length >= 2)))
    ) {
      annoSource?.setData(fc([]));
      return;
    }
    const features: GeoFeature[] = [
      {
        type: "Feature",
        properties: { icon: hazard === "flood" ? "ts-source" : "ts-epicenter" },
        geometry: { type: "Point", coordinates: [source.lng, source.lat] },
      },
    ];
    annoSource.setData(fc(features));
  }, [source, hazard, selectedRiverId, drawnRiver, mode, mapLoaded]);

  // --- quake epicenter pulse (rAF halo around the epicenter marker) ----------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (result?.kind !== "earthquake") {
      pulseRef.current = null;
      return;
    }
    let raf = 0;
    const base = pulseRef.current?.radius ?? 4;
    map.setPaintProperty(
      "ts-pulse",
      "circle-stroke-color",
      pulseRef.current?.color ?? "#E34B4B",
    );
    const t0 = performance.now();
    const step = () => {
      raf = requestAnimationFrame(step);
      const t = (performance.now() - t0) / 1000;
      const r = base + (1 - Math.cos(t * 0.9)) * 24;
      const alpha = 0.85 * Math.max(0, 1 - ((r - base) / 24) * 0.55);
      map.setPaintProperty("ts-pulse", "circle-radius", r);
      map.setPaintProperty("ts-pulse", "circle-opacity", alpha);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [result, source, mapLoaded]);

  // --- planned assets ---------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const symbolSrc = map.getSource("ts-plan-assets") as
      maplibregl.GeoJSONSource | undefined;
    const blockSrc = map.getSource("ts-plan-3d") as
      maplibregl.GeoJSONSource | undefined;
    if (mode !== "new") {
      symbolSrc?.setData(fc([]));
      blockSrc?.setData(fc([]));
      map.setLayoutProperty("ts-plan-3d", "visibility", "none");
      return;
    }
    symbolSrc?.setData(
      fc(
        placed.map((a) => ({
          type: "Feature",
          properties: {
            icon: iconForType(a.type),
            selected: a.id === selectedAssetId,
          },
          geometry: { type: "Point", coordinates: [a.lng, a.lat] },
        })),
      ),
    );
    const blocks = buildAssetBlocks(
      placed.map((a) => ({
        id: a.id,
        type: a.type,
        lng: a.lng,
        lat: a.lat,
        selected: a.id === selectedAssetId,
      })),
    );
    blockSrc?.setData(fc(applyBands(blocks, bandsFromResult(result))));
    map.setLayoutProperty(
      "ts-plan-3d",
      "visibility",
      blocks.length ? "visible" : "none",
    );
    scheduleTerrainRefresh(map);
  }, [placed, selectedAssetId, mode, result, mapLoaded]);

  // --- keep layer stacking ----------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    for (const id of LAYER_ORDER) {
      try {
        map.moveLayer(id);
      } catch {
        // layer not present yet
      }
    }
  }, [result, suitability, mode, placed, mapLoaded]);

  // --- pointer for planning ---------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (pendingAsset || drawingRiver) {
      map.getCanvas().style.cursor = "crosshair";
    } else {
      map.getCanvas().style.cursor = "";
    }
  }, [pendingAsset, drawingRiver, mapLoaded]);

  if (!webgl2.current) {
    return (
      <div className="map-canvas">
        <div className="map-unsupported">
          This browser can't render the map.
          <br />
          Enable hardware acceleration or use a recent Chrome / Edge / Firefox.
        </div>
      </div>
    );
  }

  return (
    <div className="map-shell">
      <div ref={containerRef} className="map-canvas" />
      {layersPending && <div className="map-loading-chip">loading city layers…</div>}
      {tip && (
        <div className="building-tip" style={{ left: tip.x, top: tip.y }}>
          {tip.text}
        </div>
      )}
    </div>
  );
}
