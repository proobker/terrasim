import { create } from "zustand";
import type { AssetType, CityInfo, HazardKind, PlannedAsset, RiverSummary, SimResult, SuitabilityResult } from "./types";

export type BootState = "loading" | "error" | "ready";

interface TerrasimState {
  cities: CityInfo[];
  city: CityInfo | null;
  mode: "existing" | "new";
  cityLoaded: boolean;
  bootState: BootState;

  hazard: HazardKind;
  floodLevelM: number;
  quakeMagnitude: number;
  quakeDepthKm: number;

  source: { lng: number; lat: number } | null;
  rivers: RiverSummary[];
  selectedRiverId: string | null;
  result: SimResult | null;
  running: boolean;
  runCount: number;
  error: string | null;

  suitability: SuitabilityResult | null;
  pendingAsset: AssetType | null;
  pickingOrigin: boolean;
  placed: PlannedAsset[];
  selectedAssetId: string | null;

  showRoads: boolean;
  showBuildings: boolean;
  showFacilities: boolean;
  showSuitability: boolean;
  terrain3d: boolean;
  facilityDetail: { name?: string; type?: string } | null;

  setCities: (cities: CityInfo[]) => void;
  setBootState: (s: BootState) => void;
  selectCity: (city: CityInfo | null) => void;
  setMode: (mode: "existing" | "new") => void;
  setHazard: (hazard: HazardKind) => void;
  setFloodLevelM: (v: number) => void;
  setQuakeMagnitude: (v: number) => void;
  setQuakeDepthKm: (v: number) => void;
  setSource: (lng: number, lat: number) => void;
  setRivers: (rivers: RiverSummary[]) => void;
  setSelectedRiverId: (id: string | null) => void;
  setResult: (r: SimResult | null) => void;
  setRunning: (v: boolean) => void;
  setError: (e: string | null) => void;
  setSuitability: (s: SuitabilityResult | null) => void;
  setPendingAsset: (t: AssetType | null) => void;
  addPlaced: (a: PlannedAsset) => void;
  removePlaced: (id: string) => void;
  moveSelectedPlaced: (lng: number, lat: number) => void;
  clearPlaced: () => void;
  selectAsset: (id: string | null) => void;
  setShowRoads: (v: boolean) => void;
  setShowBuildings: (v: boolean) => void;
  setShowFacilities: (v: boolean) => void;
  setShowSuitability: (v: boolean) => void;
  setTerrain3d: (v: boolean) => void;
  setFacilityDetail: (d: { name?: string; type?: string } | null) => void;
  setPickingOrigin: (v: boolean) => void;
}

export const useStore = create<TerrasimState>((set) => ({
  cities: [],
  city: null,
  mode: "existing",
  cityLoaded: false,
  bootState: "loading",

  hazard: "earthquake",
  floodLevelM: 2,
  quakeMagnitude: 6.5,
  quakeDepthKm: 10,

  source: null,
  rivers: [],
  selectedRiverId: null,
  result: null,
  running: false,
  runCount: 0,
  error: null,

  suitability: null,
  pendingAsset: null,
  pickingOrigin: false,
  placed: [],
  selectedAssetId: null,

  showRoads: true,
  showBuildings: true,
  showFacilities: true,
  showSuitability: true,
  terrain3d: true,
  facilityDetail: null,

  setCities: (cities) => set({ cities }),
  setBootState: (bootState) => set({ bootState }),
  selectCity: (city) => set({ city, source: null, rivers: [], selectedRiverId: null, result: null, suitability: null, runCount: 0 }),
  setMode: (mode) => set({ mode, result: null }),
  setHazard: (hazard) => set({ hazard, result: null }),
  setFloodLevelM: (floodLevelM) => set({ floodLevelM }),
  setQuakeMagnitude: (quakeMagnitude) => set({ quakeMagnitude }),
  setQuakeDepthKm: (quakeDepthKm) => set({ quakeDepthKm }),
  setSource: (lng, lat) => set({ source: { lng, lat }, result: null }),
  setRivers: (rivers) => set({ rivers }),
  setSelectedRiverId: (selectedRiverId) => set({ selectedRiverId, result: null }),
  setResult: (result) => set((s) => ({ result, runCount: s.runCount + 1 })),
  setRunning: (running) => set({ running }),
  setError: (error) => set({ error }),
  setSuitability: (suitability) => set({ suitability }),
  setPendingAsset: (pendingAsset) => set({ pendingAsset }),
  addPlaced: (a) => set((s) => ({ placed: [...s.placed, a] })),
  removePlaced: (id) => set((s) => ({ placed: s.placed.filter((a) => a.id !== id) })),
  moveSelectedPlaced: (lng, lat) =>
    set((s) => ({
      placed: s.placed.map((a) => (a.id === s.selectedAssetId ? { ...a, lng, lat } : a)),
    })),
  clearPlaced: () => set({ placed: [], selectedAssetId: null }),
  selectAsset: (selectedAssetId) => set({ selectedAssetId }),
  setShowRoads: (showRoads) => set({ showRoads }),
  setShowBuildings: (showBuildings) => set({ showBuildings }),
  setShowFacilities: (showFacilities) => set({ showFacilities }),
  setShowSuitability: (showSuitability) => set({ showSuitability }),
  setTerrain3d: (terrain3d) => set({ terrain3d }),
  setFacilityDetail: (facilityDetail) => set({ facilityDetail }),
  setPickingOrigin: (pickingOrigin) => set({ pickingOrigin }),
}));