import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";

// maplibre v6 resolves its worker URL from import.meta.url, which a bundler
// rewrites so the sibling worker file is never served. Point it at the worker
// Vite emits/`?worker&url`-bundles before any Map is constructed.
maplibregl.setWorkerUrl(maplibreWorkerUrl);
import { api } from "./api";
import { atlasDefinitions, iconForType } from "./pixelIcons";
import { useStore } from "./store";
import type { FeatureCollection, GeoFeature } from "./types";

// Layer order, bottom -> top. Re-applied whenever a layer is added/removed.
const LAYER_ORDER = [
  "ts-sus-red",
  "ts-sus-yellow",
  "ts-sus-green",
  "ts-water",
  "ts-river-sel",
  "ts-overlay",
  "ts-flood-shore",
  "ts-infra-buildings",
  "ts-infra-roads",
  "ts-infra-facilities",
  "ts-exposed-dots",
  "ts-plan-assets",
  "ts-pulse",
  "ts-annos",
];

const QUIET_SRC = {
  type: "geojson",
  data: { type: "FeatureCollection", features: [] },
} as const;

function fc(features: GeoFeature[]): FeatureCollection {
  return { type: "FeatureCollection", features };
}

function webgl2Available(): boolean {
  try {
    return !!document.createElement("canvas").getContext("webgl2");
  } catch {
    return false;
  }
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
      tileSize: 256,
      minzoom: 7,
      maxzoom: 15,
      bounds,
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
  const showRoads = useStore((s) => s.showRoads);
  const showBuildings = useStore((s) => s.showBuildings);
  const showFacilities = useStore((s) => s.showFacilities);
  const showSuitability = useStore((s) => s.showSuitability);
  const terrain3d = useStore((s) => s.terrain3d);
  // OSM ids -> facility features, for tinting exposed assets after a run.
  const facilitiesRef = useRef<Map<string, GeoFeature>>(new Map());
  // Water-layer features keyed by OSM id, for drawing the selected river.
  const waterRef = useRef<Map<string, GeoFeature>>(new Map());
  // Brush used to draw the quake pulse halo; kept in a ref so the rAF loop
  // doesn't re-subscribe on every pixel.
  const pulseRef = useRef<{ radius: number; color: string } | null>(null);

  const setSource = useStore((s) => s.setSource);
  const setFacilityDetail = useStore((s) => s.setFacilityDetail);
  const addPlaced = useStore((s) => s.addPlaced);
  const moveSelectedPlaced = useStore((s) => s.moveSelectedPlaced);
  const selectAsset = useStore((s) => s.selectAsset);
  const setPendingAsset = useStore((s) => s.setPendingAsset);
  const setError = useStore((s) => s.setError);

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
            paint: { "raster-opacity": 0.85 },
          },
        ],
      },
      center: [85.34, 27.7],
      zoom: 12,
      attributionControl: false,
    });

    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-right",
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
        "ts-overlay",
      ]) {
        map.addSource(id, QUIET_SRC as never);
      }
      map.addSource("ts-infra-buildings", QUIET_SRC as never);
      map.addSource("ts-infra-roads", QUIET_SRC as never);
      map.addSource("ts-infra-facilities", QUIET_SRC as never);
      map.addSource("ts-plan-assets", QUIET_SRC as never);
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
        type: "circle",
        source: "ts-infra-buildings",
        paint: {
          "circle-radius": 1.6,
          "circle-color": "#314137",
          "circle-opacity": 0.8,
        },
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

    map.fitBounds(
      [
        [city.bounds[0], city.bounds[1]],
        [city.bounds[2], city.bounds[3]],
      ],
      { padding: 60, duration: 600 },
    );

    applyTerrain(map, city.id, city.bounds, useStore.getState().terrain3d);

    void Promise.all([
      api.layer(city.id, "buildings").then((data) => {
        const source = map.getSource(
          "ts-infra-buildings",
        ) as maplibregl.GeoJSONSource;
        source?.setData(data ?? fc([]));
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
    ]).catch((err: unknown) => setError(String(err)));
  }, [city, setError, mapLoaded]);

  // --- selected river highlight (flood origin by river) ----------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const selSource = map.getSource("ts-river-sel") as
      maplibregl.GeoJSONSource | undefined;
    if (!selSource) return;
    const highlight =
      hazard === "flood" && selectedRiverId && waterRef.current.has(selectedRiverId)
        ? fc([waterRef.current.get(selectedRiverId)!])
        : fc([]);
    selSource.setData(highlight);
    map.setLayoutProperty(
      "ts-river-sel",
      "visibility",
      highlight.features.length ? "visible" : "none",
    );
  }, [selectedRiverId, hazard, mapLoaded]);

  // --- infrastructure toggles ------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const setVis = (id: string, on: boolean) =>
      map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    setVis("ts-infra-buildings", showBuildings && mode === "existing");
    setVis("ts-infra-roads", showRoads && mode === "existing");
    setVis("ts-infra-facilities", showFacilities && mode === "existing");
  }, [showRoads, showBuildings, showFacilities, mode, mapLoaded]);

  // --- terrain elevation ------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded || !city) return;
    applyTerrain(map, city.id, city.bounds, terrain3d);
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
  }, [result, mapLoaded]);

  // --- annotations (flood source / epicenter) --------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    const annoSource = map.getSource("ts-annos") as
      maplibregl.GeoJSONSource | undefined;
    // A selected river is drawn as its own highlight; a point marker would
    // only be a fallback origin in that case.
    if (!source || !annoSource || (hazard === "flood" && selectedRiverId)) {
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
  }, [source, hazard, selectedRiverId, mode, mapLoaded]);

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
    const source = map.getSource("ts-plan-assets") as
      maplibregl.GeoJSONSource | undefined;
    if (mode !== "new") {
      source?.setData(fc([]));
      return;
    }
    source?.setData(
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
  }, [placed, selectedAssetId, mode, mapLoaded]);

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
    if (pendingAsset) {
      map.getCanvas().style.cursor = "crosshair";
    } else {
      map.getCanvas().style.cursor = "";
    }
  }, [pendingAsset, mapLoaded]);

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

  return <div ref={containerRef} className="map-canvas" />;
}
