import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { api } from "./api";
import { atlasDefinitions, iconForType } from "./pixelIcons";
import { useStore } from "./store";
import type { FeatureCollection, GeoFeature } from "./types";

// Layer order, bottom -> top. Re-applied whenever a layer is added/removed.
const LAYER_ORDER = [
  "ts-sus-red",
  "ts-sus-yellow",
  "ts-sus-green",
  "ts-overlay",
  "ts-infra-buildings",
  "ts-infra-roads",
  "ts-infra-facilities",
  "ts-plan-assets",
  "ts-annos",
];

const QUIET_SRC = { type: "geojson", data: { type: "FeatureCollection", features: [] } } as const;

function fc(features: GeoFeature[]): FeatureCollection {
  return { type: "FeatureCollection", features };
}

export default function MapView({ onReady }: { onReady?: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const initializedCity = useRef<string | null>(null);

  const city = useStore((s) => s.city);
  const mode = useStore((s) => s.mode);
  const hazard = useStore((s) => s.hazard);
  const source = useStore((s) => s.source);
  const result = useStore((s) => s.result);
  const suitability = useStore((s) => s.suitability);
  const placed = useStore((s) => s.placed);
  const pendingAsset = useStore((s) => s.pendingAsset);
  const selectedAssetId = useStore((s) => s.selectedAssetId);
  const showRoads = useStore((s) => s.showRoads);
  const showBuildings = useStore((s) => s.showBuildings);
  const showFacilities = useStore((s) => s.showFacilities);
  const showSuitability = useStore((s) => s.showSuitability);

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

    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    const atlas = atlasDefinitions();
    for (const [name, image] of Object.entries(atlas)) {
      const imageData = new ImageData(new Uint8ClampedArray(image.data), image.width, image.height);
      map.addImage(name, imageData);
    }

    // static (empty) sources
    for (const id of ["ts-sus-green", "ts-sus-yellow", "ts-sus-red", "ts-overlay"]) {
      map.addSource(id, QUIET_SRC as never);
    }
    map.addSource("ts-infra-buildings", QUIET_SRC as never);
    map.addSource("ts-infra-roads", QUIET_SRC as never);
    map.addSource("ts-infra-facilities", QUIET_SRC as never);
    map.addSource("ts-plan-assets", QUIET_SRC as never);
    map.addSource("ts-annos", QUIET_SRC as never);

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
      id: "ts-overlay",
      type: "fill",
      source: "ts-overlay",
      paint: {
        "fill-color": [
          "match",
          ["get", "class"],
          "high", "#E34B4B",
          "medium_high", "#E59B45",
          "medium", "#E6C66A",
          "low", "#159A9C",
          "flood", "#43C7D8",
          "#43C7D8",
        ],
        "fill-opacity": [
          "match",
          ["get", "class"],
          "flood", 0.55,
          0.34,
        ],
      },
      layout: { visibility: "none" },
    });
    map.addLayer({
      id: "ts-infra-buildings",
      type: "circle",
      source: "ts-infra-buildings",
      paint: { "circle-radius": 1.6, "circle-color": "#314137", "circle-opacity": 0.8 },
    });
    map.addLayer({
      id: "ts-infra-roads",
      type: "line",
      source: "ts-infra-roads",
      paint: { "line-color": "#d9b957", "line-width": 1.3, "line-opacity": 0.85 },
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
      id: "ts-annos",
      type: "symbol",
      source: "ts-annos",
      layout: { "icon-image": ["get", "icon"], "icon-size": 0.9, "icon-allow-overlap": true },
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
      setFacilityDetail({ name: (props.name as string) ?? "", type: (props.type as string) ?? "" });
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
    if (!map || !city) return;
    if (initializedCity.current === city.id) return;
    initializedCity.current = city.id;

    map.fitBounds(
      [
        [city.bounds[0], city.bounds[1]],
        [city.bounds[2], city.bounds[3]],
      ],
      { padding: 60, duration: 600 },
    );

    void Promise.all([
      api.layer(city.id, "buildings").then((data) => {
        const source = map.getSource("ts-infra-buildings") as maplibregl.GeoJSONSource;
        source?.setData(data ?? fc([]));
      }),
      api.layer(city.id, "roads").then((data) => {
        const source = map.getSource("ts-infra-roads") as maplibregl.GeoJSONSource;
        source?.setData(data ?? fc([]));
      }),
      api.layer(city.id, "facilities").then((data) => {
        const features = (data?.features ?? []).map((f) => ({
          ...f,
          properties: { ...f.properties, icon: iconForType((f.properties.type as string) ?? "") },
        }));
        const source = map.getSource("ts-infra-facilities") as maplibregl.GeoJSONSource;
        source?.setData(fc(features));
      }),
    ]).catch((err: unknown) => setError(String(err)));
  }, [city, setError]);

  // --- infrastructure toggles ------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const setVis = (id: string, on: boolean) =>
      map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    setVis("ts-infra-buildings", showBuildings && mode === "existing");
    setVis("ts-infra-roads", showRoads && mode === "existing");
    setVis("ts-infra-facilities", showFacilities && mode === "existing");
  }, [showRoads, showBuildings, showFacilities, mode]);

  // --- suitability overlay ---------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const setData = (id: string, data?: FeatureCollection | null) => {
      (map.getSource(id) as maplibregl.GeoJSONSource | undefined)?.setData(
        data ?? { type: "FeatureCollection", features: [] },
      );
    };
    setData("ts-sus-red", mode === "new" && showSuitability ? suitability?.layers.red : null);
    setData("ts-sus-yellow", mode === "new" && showSuitability ? suitability?.layers.yellow : null);
    setData("ts-sus-green", mode === "new" && showSuitability ? suitability?.layers.green : null);
    const setVis = (id: string, on: boolean) =>
      map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    setVis("ts-sus-red", Boolean(mode === "new" && showSuitability && suitability));
    setVis("ts-sus-yellow", Boolean(mode === "new" && showSuitability && suitability));
    setVis("ts-sus-green", Boolean(mode === "new" && showSuitability && suitability));
  }, [suitability, mode, showSuitability]);

  // --- hazard result overlay -------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource("ts-overlay") as maplibregl.GeoJSONSource | undefined;
    let data: FeatureCollection = fc([]);
    if (result?.kind === "flood" && !result.dry) data = result.overlay;
    if (result?.kind === "earthquake") data = result.zones;
    source?.setData(data);
    map.setLayoutProperty("ts-overlay", "visibility", data.features.length ? "visible" : "none");
  }, [result]);

  // --- annotations (flood source / epicenter) --------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const annoSource = map.getSource("ts-annos") as maplibregl.GeoJSONSource | undefined;
    if (!source || !annoSource) {
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
  }, [source, hazard, mode]);

  // --- planned assets ---------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource("ts-plan-assets") as maplibregl.GeoJSONSource | undefined;
    if (mode !== "new") {
      source?.setData(fc([]));
      return;
    }
    source?.setData(
      fc(
        placed.map((a) => ({
          type: "Feature",
          properties: { icon: iconForType(a.type), selected: a.id === selectedAssetId },
          geometry: { type: "Point", coordinates: [a.lng, a.lat] },
        })),
      ),
    );
  }, [placed, selectedAssetId, mode]);

  // --- keep layer stacking ----------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const id of LAYER_ORDER) {
      try {
        map.moveLayer(id);
      } catch {
        // layer not present yet
      }
    }
  }, [result, suitability, mode, placed]);

  // --- pointer for planning ---------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (pendingAsset) {
      map.getCanvas().style.cursor = "crosshair";
    } else {
      map.getCanvas().style.cursor = "";
    }
  }, [pendingAsset]);

  return <div ref={containerRef} className="map-canvas" />;
}