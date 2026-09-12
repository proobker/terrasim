import { api } from "./api";
import { useStore } from "./store";
import { useCallback, useRef } from "react";
import type { PlannedAsset } from "./types";

function pickHazardSource() {
  const s = useStore.getState();
  if (s.source) return s.source;
  s.setError("Set a hazard origin on the map first — pick a river or tap the map to place the flood source / epicenter.");
  return null;
}

function planAssets(placed: PlannedAsset[]) {
  return placed.map((a) => ({
    kind: a.type,
    id: a.id,
    name: a.type.replace("_", " "),
    lng: a.lng,
    lat: a.lat,
  }));
}

export function useSimulate() {
  const city = useStore((s) => s.city);
  const mode = useStore((s) => s.mode);
  const hazard = useStore((s) => s.hazard);
  const floodLevelM = useStore((s) => s.floodLevelM);
  const quakeMagnitude = useStore((s) => s.quakeMagnitude);
  const quakeDepthKm = useStore((s) => s.quakeDepthKm);
  const placed = useStore((s) => s.placed);
  const selectedRiverId = useStore((s) => s.selectedRiverId);

  const run = useStore((s) => s.setRunning);
  const setResult = useStore((s) => s.setResult);
  const setError = useStore((s) => s.setError);

  async function runHazard() {
    if (!city) return;
    const useRiver = hazard === "flood" && Boolean(selectedRiverId);
    const origin = useRiver ? null : pickHazardSource();
    if (!useRiver && !origin) return;

    const assets = mode === "new" && placed.length ? planAssets(placed) : null;
    run(true);
    setError(null);
    try {
      const result =
        hazard === "flood"
          ? await api.flood({
              city_id: city.id,
              ...(useRiver ? { river_id: selectedRiverId! } : { source: origin! }),
              level_m: floodLevelM,
              mode: "rise",
              assets,
            })
          : await api.quake({
              city_id: city.id,
              epicenter: origin!,
              magnitude: quakeMagnitude,
              depth_km: quakeDepthKm,
              assets,
            });
      setResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      run(false);
    }
  }

  return {
    hazard,
    runHazard,
    canRun: Boolean(city),
    running: useStore((s) => s.running),
    needsAssets: mode === "new" && placed.length === 0,
    hasOrigin:
      hazard === "flood"
        ? Boolean(selectedRiverId || useStore((s) => s.source))
        : Boolean(useStore((s) => s.source)),
  };
}

export function useRivers() {
  const city = useStore((s) => s.city);
  const setRivers = useStore((s) => s.setRivers);
  const setError = useStore((s) => s.setError);
  const loadedFor = useRef<string | null>(null);

  const load = useCallback(async () => {
    if (!city) return;
    if (loadedFor.current === city.id && useStore.getState().rivers.length) return;
    loadedFor.current = city.id;
    try {
      setRivers(await api.rivers(city.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [city, setRivers, setError]);

  return { load, rivers: useStore((s) => s.rivers) };
}

export function useSuitability() {
  const city = useStore((s) => s.city);
  const suitability = useStore((s) => s.suitability);
  const setSuitability = useStore((s) => s.setSuitability);
  const setError = useStore((s) => s.setError);

  async function load() {
    if (!city) return;
    if (suitability) return;
    try {
      setSuitability(await api.suitability(city.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return { load, suitability };
}