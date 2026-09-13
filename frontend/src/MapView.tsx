import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";

// maplibre v6 resolves its worker URL from import.meta.url, which a bundler
// rewrites so the sibling worker file is never served. Point it at the worker
// Vite emits/`?worker&url`-bundles before any Map is constructed.
maplibregl.setWorkerUrl(maplibreWorkerUrl);
import { api } from "./api";
import { applyBands, bandsFromResult, buildAssetBlocks, buildBlockFeatures } from "./buildings3d";
import { atlasDefinitions, iconForType } from "./pixelIcons";
import { useStore } from "./store";
import type { BlockFeature } from "./buildings3d";
import type { FeatureCollection, GeoFeature, PointLngLat } from "./types";

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
  "ts-infra-buildings",
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
    return !!document.createElement("canvas").getContext("webgl2");
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

// The DEM/tile renderer mirrors the backend's coverage padding (PAD_FRAC).
const DEM_PAD = 0.5;

function padBounds(
  bounds: [number, number, number, number],
): [number, number, number, number] {
  const dx = (bounds[2] - bounds[0]) * DEM_PAD;
  const dy = (bounds[3] - bounds[1]) * DEM_PAD;
  return [bounds[0] - dx, bounds[1] - dy, bounds[2] + dx, bounds[3] + dy];
}

function applyTerrain(
  map: maplibregl.Map,
  cityId: string,
  bounds: [number, number, number, number],
  enabled: boolean,
) {
  const existing = map.getSource("dem") as
    | maplibregl.RasterDEMTileSource
    | undefined;
  const tiles = [api.terrainUrl(cityId)];
  if (existing) {
    existing.setTiles(tiles);
  } else {
    map.addSource("dem", {
      type: "raster-dem",
      tiles,
      // DEM tiles are 512px and maplibre v6 terrain composites each to a 2x
      // RTT of the *declared* size — declare the true tile size so the mesh
      // grid lines up with the draped raster instead of smearing it.
      tileSize: 512,
      minzoom: 7,
      maxzoom: 15,
      bounds: padBounds(bounds),
      encoding: "terrarium",
    });
  }
  if (enabled) {
    map.setTerrain({ source: "dem", exaggeration: 1.3 });
    map.setSky({
      "sky-color": "#0f1b3a",
      "horizon-color": "#8fb4c4",
      "fog-color": "#dde5e6",
      "fog-ground-blend": 0.55,
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

export default function MapView({ onReady }: { onReady?: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const initializedCity = useRef<string | null>(null);
  const webgl2 = useRef<boolean>(webgl2Available());
  // maplibre v6 only allows style mutations after the style has loaded.
  const [mapLoaded, setMapLoaded] = useState(false);
  // Hover label over the voxel blocks (position + copy).
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);

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
  // Raw centroid buildings (per city) and their stylised 3D block features.
  const buildingsRef = useRef<GeoFeature[]>([]);
  const blocksRef = useRef<BlockFeature[]>([]);
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
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
            maxzoom: 19,
          },
        },
        layers: [
          {
            id: "ts-osm",
            type: "raster",
            source: "osm",
            // FireRed treatment: pull the stock OSM tiles toward the muted
            // greens/teals of the palette so they read as a stylised base
            // under the voxel blocks, not a default-looking web map.
            paint: {
              "raster-opacity": 0.55,
              "raster-saturation": -0.6,
              "raster-hue-rotate": 55,
              "raster-brightness-min": 0.78,
              "raster-brightness-max": 0.98,
              "raster-contrast": 0.15,
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
      attributionControl: false,
      canvasContextAttributes: { antialias: true },
    });

    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-right",
    );
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "bottom-left",
    );

    // Surface fatal map errors instead of a silent blank canvas. Tile-level
    // failures (e.g. a slow tile server) are warnings, not toasts.
    map.on("error", (e) => {
      const ev = e as unknown as {
        error?: { message?: string };
        message?: unknown;
      };
      const msg = ev.error?.message ?? (typeof ev.message === "string" ? ev.message : String(e));
      if (!map.isStyleLoaded()) {
        setError(`Map failed to start: ${msg}`);
      } else {
        console.warn("[terrasim map]", msg);
      }
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
      map.addSource("ts-infra-buildings", QUIET_SRC as never);
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
          "fill-opacity": ["match", ["get", "class"], "flood-deep", 0.7, "flood", 0.55, 0.34],
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
        id: "ts-infra-buildings",
        type: "fill-extrusion",
        source: "ts-infra-buildings",
        paint: {
          // A hazard band (from a sim run) tints the whole block; silent
          // blocks keep their silhouette colour.
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

      onReady?.();
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
      const band = p.band as string | undefined;
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
    map.on("mousemove", "ts-infra-buildings", (e) =>
      tipFrom(e, e.features?.[0]),
    );
    map.on("mouseleave", "ts-infra-buildings", (e) => tipFrom(e, undefined));
    map.on("mousemove", "ts-plan-3d", (e) => tipFrom(e, e.features?.[0]));
    map.on("mouseleave", "ts-plan-3d", (e) => tipFrom(e, undefined));

    mapRef.current = map;
    onReady?.();
    return () => {
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
    map.fitBounds(
      [
        [target[0], target[1]],
        [target[2], target[3]],
      ],
      { padding: 60, duration: 600 },
    );
    // The fitBounds camera sweep churns terrain RTT caches unevenly; recompose
    // everything once it settles so no flat tile lingers at rest.
    map.once("moveend", () => scheduleTerrainRefresh(map));

    applyTerrain(
      map,
      city.id,
      city.hazard_bounds ?? (city.bounds as [number, number, number, number]),
      useStore.getState().terrain3d,
    );

    void Promise.all([
      api.layer(city.id, "buildings").then((data) => {
        const raw = data?.features ?? [];
        buildingsRef.current = raw;
        blocksRef.current = buildBlockFeatures(raw);
        const source = map.getSource(
          "ts-infra-buildings",
        ) as maplibregl.GeoJSONSource | undefined;
        source?.setData(fc(blocksRef.current));
      }),
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
    ]).then(() => scheduleTerrainRefresh(map))
      .catch((err: unknown) => setError(String(err)));
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
    setVis(
      "ts-infra-buildings",
      showBuildings && showBlocky3d && mode === "existing",
    );
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
    applyTerrain(
      map,
      city.id,
      city.hazard_bounds ?? (city.bounds as [number, number, number, number]),
      terrain3d,
    );
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

    const buildingSrc = map.getSource("ts-infra-buildings") as
      | maplibregl.GeoJSONSource
      | undefined;
    buildingSrc?.setData(fc(applyBands(blocksRef.current, bandsFromResult(result))));
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
      {tip && (
        <div className="building-tip" style={{ left: tip.x, top: tip.y }}>
          {tip.text}
        </div>
      )}
    </div>
  );
}
