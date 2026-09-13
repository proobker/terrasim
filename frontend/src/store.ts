import { create } from "zustand";
import type { AssetType, CityInfo, DrawnRiver, HazardKind, PlannedAsset, RiverSummary, SimResult, SuitabilityResult } from "./types";

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
  stampGrid: number | null;
  drawnRiver: DrawnRiver | null;
  drawingRiver: boolean;
  placed: PlannedAsset[];
  selectedAssetId: string | null;

  showRoads: boolean;
  showBuildings: boolean;
  showFacilities: boolean;
  showSuitability: boolean;
  terrain3d: boolean;
  showBlocky3d: boolean;
  showValleyRim: boolean;
  rimAvailable: boolean;
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
  setStampGrid: (n: number | null) => void;
  setDrawnRiver: (r: DrawnRiver | null) => void;
  appendDrawPoint: (p: { lng: number; lat: number }) => void;
  undoDrawPoint: () => void;
  clearDrawn: () => void;
  setDrawing: (v: boolean) => void;
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
  setShowBlocky3d: (v: boolean) => void;
  setShowValleyRim: (v: boolean) => void;
  setRimAvailable: (v: boolean) => void;
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
  stampGrid: null,
  drawnRiver: null,
  drawingRiver: false,
  placed: [],
  selectedAssetId: null,

  showRoads: true,
  showBuildings: true,
  showFacilities: true,
  showSuitability: true,
  terrain3d: true,
  showBlocky3d: true,
  showValleyRim: true,
  rimAvailable: false,
  facilityDetail: null,

  setCities: (cities) => set({ cities }),
  setBootState: (bootState) => set({ bootState }),
  selectCity: (city) =>
    set({
      city,
      source: null,
      rivers: [],
      selectedRiverId: null,
      drawnRiver: null,
      drawingRiver: false,
      result: null,
      suitability: null,
      runCount: 0,
    }),
  setMode: (mode) => set({ mode, result: null }),
  setHazard: (hazard) => set({ hazard, result: null }),
  setFloodLevelM: (floodLevelM) => set({ floodLevelM }),
  setQuakeMagnitude: (quakeMagnitude) => set({ quakeMagnitude }),
  setQuakeDepthKm: (quakeDepthKm) => set({ quakeDepthKm }),
  setSource: (lng, lat) => set({ source: { lng, lat }, result: null }),
  setRivers: (rivers) => set({ rivers }),
  setSelectedRiverId: (selectedRiverId) =>
    set((s) => ({
      selectedRiverId,
      drawnRiver: selectedRiverId ? null : s.drawnRiver,
      result: null,
    })),
  setResult: (result) => set((s) => ({ result, runCount: s.runCount + 1 })),
  setRunning: (running) => set({ running }),
  setError: (error) => set({ error }),
  setSuitability: (suitability) => set({ suitability }),
  setPendingAsset: (pendingAsset) => set({ pendingAsset }),
  setStampGrid: (stampGrid) => set({ stampGrid }),
  setDrawnRiver: (drawnRiver) =>
    set({ drawnRiver, selectedRiverId: null, source: null, result: null }),
  appendDrawPoint: (p) =>
    set((s) => ({
      drawnRiver: { path: s.drawnRiver ? [...s.drawnRiver.path, p] : [p] },
      selectedRiverId: null,
      result: null,
    })),
  undoDrawPoint: () =>
    set((s) => ({
      drawnRiver:
        s.drawnRiver && s.drawnRiver.path.length > 1
          ? { path: s.drawnRiver.path.slice(0, -1) }
          : null,
    })),
  clearDrawn: () => set({ drawnRiver: null }),
  setDrawing: (drawingRiver) => set({ drawingRiver }),
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
  setShowBlocky3d: (showBlocky3d) => set({ showBlocky3d }),
  setShowValleyRim: (showValleyRim) => set({ showValleyRim }),
  setRimAvailable: (rimAvailable) => set({ rimAvailable }),
  setFacilityDetail: (facilityDetail) => set({ facilityDetail }),
  setPickingOrigin: (pickingOrigin) => set({ pickingOrigin }),
}));