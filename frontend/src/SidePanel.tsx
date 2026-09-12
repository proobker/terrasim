import { useEffect, useRef } from "react";
import ExposurePanel from "./ExposurePanel";
import { drawPreviewInto } from "./pixelIcons";
import { useStore } from "./store";
import { useRivers, useSimulate, useSuitability } from "./useSimulate";

const ASSET_TYPES = [
  { type: "hospital" as const, name: "Hospital" },
  { type: "school" as const, name: "School" },
  { type: "housing" as const, name: "Residential" },
  { type: "fire_station" as const, name: "Fire Station" },
  { type: "police" as const, name: "Police" },
  { type: "shelter" as const, name: "Shelter" },
];

function LayerToggles() {
  const showRoads = useStore((s) => s.showRoads);
  const showBuildings = useStore((s) => s.showBuildings);
  const showFacilities = useStore((s) => s.showFacilities);
  const terrain3d = useStore((s) => s.terrain3d);
  const setShowRoads = useStore((s) => s.setShowRoads);
  const setShowBuildings = useStore((s) => s.setShowBuildings);
  const setShowFacilities = useStore((s) => s.setShowFacilities);
  const setTerrain3d = useStore((s) => s.setTerrain3d);
  return (
    <div>
      <div className="pixel-label" style={{ marginBottom: 6 }}>
        Infrastructure overlay
      </div>
      <div className="field-row" style={{ margin: 0 }}>
        {(
          [
            ["roads", showRoads, setShowRoads],
            ["buildings", showBuildings, setShowBuildings],
            ["facilities", showFacilities, setShowFacilities],
            ["3D terrain", terrain3d, setTerrain3d],
          ] as [string, boolean, (v: boolean) => void][]
        ).map(([label, on, setOn]) => (
          <label key={label} style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={on}
              onChange={() => setOn(!on)}
              style={{ accentColor: "#159A9C", width: 16, height: 16 }}
            />
            <span style={{ fontSize: 13, textTransform: "capitalize" }}>{label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

function FloodOriginPicker() {
  const rivers = useStore((s) => s.rivers);
  const selectedRiverId = useStore((s) => s.selectedRiverId);
  const setSelectedRiverId = useStore((s) => s.setSelectedRiverId);
  return (
    <div className="field-row" style={{ margin: 0, flexDirection: "column", alignItems: "stretch", gap: 6 }}>
      <span className="pixel-label">Flood origin</span>
      <select
        className="pixel-select"
        value={selectedRiverId ?? ""}
        onChange={(e) => setSelectedRiverId(e.target.value || null)}
      >
        <option value="">Tap the map to set a point</option>
        {rivers.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name || `${r.type ?? "river"} · ${r.id}`}
          </option>
        ))}
      </select>
      <div className="mini-note">
        Pick a river to flood along its flow path, or tap the map for a point origin. Water is routed downhill along
        the river's channel and rises above each reach's local bed — a terrain-based hypothetical extent, not a forecast.
      </div>
    </div>
  );
}

function HazardControls() {
  const hazard = useStore((s) => s.hazard);
  const setHazard = useStore((s) => s.setHazard);
  const floodLevelM = useStore((s) => s.floodLevelM);
  const setFloodLevelM = useStore((s) => s.setFloodLevelM);
  const quakeMagnitude = useStore((s) => s.quakeMagnitude);
  const setQuakeMagnitude = useStore((s) => s.setQuakeMagnitude);
  const quakeDepthKm = useStore((s) => s.quakeDepthKm);
  const setQuakeDepthKm = useStore((s) => s.setQuakeDepthKm);
  const { runHazard, running } = useSimulate();

  return (
    <>
      <div className="pixel-label">Hypothetical disaster</div>
      <div className="field-row" style={{ margin: 0, justifyContent: "flex-start" }}>
        <button className="hazard-chip chip-flood" data-active={hazard === "flood"} onClick={() => setHazard("flood")}>
          Flood
        </button>
        <button className="hazard-chip chip-quake" data-active={hazard === "earthquake"} onClick={() => setHazard("earthquake")}>
          Earthquake
        </button>
      </div>

      {hazard === "flood" && (
        <>
          <FloodOriginPicker />
          <div className="field-row">
            <span className="pixel-label">River rise</span>
            <input
              className="pixel-range"
              type="range"
              min={0.5}
              max={8}
              step={0.5}
              value={floodLevelM}
              onChange={(e) => setFloodLevelM(Number(e.target.value))}
            />
            <span className="range-label">{floodLevelM.toFixed(1)} m</span>
          </div>
        </>
      )}
      {hazard !== "flood" && (
        <>
          <div className="field-row">
            <span className="pixel-label">Magnitude</span>
            <input
              className="pixel-range"
              type="range"
              min={4.5}
              max={8.5}
              step={0.1}
              value={quakeMagnitude}
              onChange={(e) => setQuakeMagnitude(Number(e.target.value))}
            />
            <span className="range-label">M {quakeMagnitude.toFixed(1)}</span>
          </div>
          <div className="field-row">
            <span className="pixel-label">Depth</span>
            <input
              className="pixel-range"
              type="range"
              min={2}
              max={30}
              step={1}
              value={quakeDepthKm}
              onChange={(e) => setQuakeDepthKm(Number(e.target.value))}
            />
            <span className="range-label">{quakeDepthKm} km</span>
          </div>
        </>
      )}

      <button className="pixel-btn primary" onClick={runHazard} disabled={running}>
        {running ? "Running…" : "▶ Run scenario"}
      </button>
    </>
  );
}

function AssetCell({ type, name }: { type: (typeof ASSET_TYPES)[number]["type"]; name: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const pendingAsset = useStore((s) => s.pendingAsset);
  const setPendingAsset = useStore((s) => s.setPendingAsset);
  useEffect(() => {
    if (ref.current) drawPreviewInto(type, ref.current);
  }, [type]);
  return (
    <button
      className="asset-cell"
      data-active={pendingAsset === type}
      onClick={() => setPendingAsset(pendingAsset === type ? null : type)}
    >
      <canvas
        ref={ref}
        width={36}
        height={36}
        style={{ width: 30, height: 30 }}
      />
      <span className="a-name">{name}</span>
    </button>
  );
}

function PlaceControls() {
  const placed = useStore((s) => s.placed);
  const selectedAssetId = useStore((s) => s.selectedAssetId);
  const removePlaced = useStore((s) => s.removePlaced);
  const clearPlaced = useStore((s) => s.clearPlaced);
  const selectAsset = useStore((s) => s.selectAsset);
  const source = useStore((s) => s.source);
  const hazard = useStore((s) => s.hazard);
  const pickingOrigin = useStore((s) => s.pickingOrigin);
  const setPickingOrigin = useStore((s) => s.setPickingOrigin);
  const selectedRiverId = useStore((s) => s.selectedRiverId);
  const { runHazard, running } = useSimulate();

  return (
    <>
      <div className="pixel-label">Place proposed facilities</div>
      <div className="asset-grid">
        {ASSET_TYPES.map((a) => (
          <AssetCell key={a.type} type={a.type} name={a.name} />
        ))}
      </div>
      <div className="mini-note">
        Select a tile, then tap the map to drop it. Tap a placed facility to move it.
      </div>

      {placed.length > 0 && (
        <div>
          <div className="pixel-label" style={{ marginBottom: 6 }}>
            Proposed layout ({placed.length})
          </div>
          {placed.map((a) => (
            <div
              className="expo-row"
              key={a.id}
              onClick={() => selectAsset(a.id === selectedAssetId ? null : a.id)}
              style={{ cursor: "pointer", background: a.id === selectedAssetId ? "#d9f3f4" : undefined }}
            >
              <span className="e-name" style={{ textTransform: "capitalize" }}>
                {a.type.replace("_", " ")}
              </span>
              <span className="e-kind">
                {a.lat.toFixed(5)}, {a.lng.toFixed(5)}
              </span>
              <button
                className="pixel-btn tiny danger"
                onClick={(e) => {
                  e.stopPropagation();
                  removePlaced(a.id);
                }}
              >
                ×
              </button>
            </div>
          ))}
          <button className="pixel-btn tiny" onClick={clearPlaced} style={{ marginTop: 6 }}>
            Clear all
          </button>
        </div>
      )}

      <div className="divider" />

      <div className="pixel-label">Hypothetical disaster</div>
      <div className="field-row" style={{ margin: 0, justifyContent: "flex-start" }}>
        <button className="hazard-chip chip-flood" data-active={hazard === "flood"} onClick={() => useStore.getState().setHazard("flood")}>
          Flood
        </button>
        <button className="hazard-chip chip-quake" data-active={hazard === "earthquake"} onClick={() => useStore.getState().setHazard("earthquake")}>
          Earthquake
        </button>
      </div>

      {hazard === "flood" && <FloodOriginPicker />}

      <button
        className="pixel-btn"
        data-active={pickingOrigin}
        onClick={() => setPickingOrigin(!pickingOrigin)}
        style={pickingOrigin ? { background: "var(--gold)" } : undefined}
      >
        {source
          ? hazard === "flood"
            ? "↻ Flood point set"
            : "↻ Epicenter set"
          : hazard === "flood"
            ? selectedRiverId
              ? "↻ River selected"
              : "Set flood origin…"
            : "Set epicenter…"}
      </button>
      <div className="mini-note">
        {pickingOrigin
          ? "Tap the map to place the hazard origin."
          : hazard === "flood" && selectedRiverId
            ? "The selected river will flood — tap the map to also set a point fallback."
            : hazard === "flood"
              ? "Pick a river above, or tap the map to set a point flood origin."
              : "Then pick a point on the map for the epicenter."}
      </div>

      <button className="pixel-btn primary" onClick={runHazard} disabled={running}>
        {running ? "Running…" : "▶ Run scenario"}
      </button>
    </>
  );
}

export default function SidePanel() {
  const mode = useStore((s) => s.mode);
  const city = useStore((s) => s.city);
  const suitability = useStore((s) => s.suitability);
  const showSuitability = useStore((s) => s.showSuitability);
  const setShowSuitability = useStore((s) => s.setShowSuitability);
  const { load } = useSuitability();
  const { load: loadRivers } = useRivers();
  const pickingOrigin = useStore((s) => s.pickingOrigin);
  const hazard = useStore((s) => s.hazard);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadRivers();
  }, [loadRivers]);

  return (
    <div className="side-panel">
      {mode === "existing" ? (
        <section className="pixel-panel">
          <div className="panel-body">
            <div className="chrome-title">Scenario Lab</div>
            <div className="mini-note">
              {city ? `${city.name} · existing assets from OpenStreetMap.` : "No city on server."}
            </div>
            <HazardControls />
            <div className="divider" />
            <LayerToggles />
            <div className="divider" />
            <div className="pixel-label" style={{ marginBottom: 6 }}>
              Map legend
            </div>
            {hazard === "flood" ? (
              <>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#43C7D8" }} /> estimated water (shallow)
                </div>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#1E7A99" }} /> deeper modelled core (≥ 1 m)
                </div>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#9BE8F2" }} /> shoreline
                </div>
              </>
            ) : (
              <>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#E34B4B" }} /> high relative intensity
                </div>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#E59B45" }} /> medium-high
                </div>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#E6C66A" }} /> medium
                </div>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#159A9C" }} /> low
                </div>
              </>
            )}
          </div>
        </section>
      ) : (
        <section className="pixel-panel">
          <div className="panel-body">
            <div className="chrome-title">Land Planning</div>
            <div className="mini-note">
              {city ? `${city.name} · suitability is a relative guide from elevation, slope and road access.` : ""}
            </div>
            {suitability && (
              <>
                <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={showSuitability}
                    onChange={() => setShowSuitability(!showSuitability)}
                    style={{ accentColor: "#159A9C", width: 16, height: 16 }}
                  />
                  <span style={{ fontSize: 13 }}>Show suitability zones</span>
                </label>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#55B86A" }} /> relatively suitable
                </div>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#E59B45" }} /> conditional / investigate
                </div>
                <div className="legend-row">
                  <span className="swatch" style={{ background: "#E34B4B" }} /> relatively higher risk
                </div>
              </>
            )}
            <div className="divider" />
            <PlaceControls />
          </div>
        </section>
      )}

      {pickingOrigin && (
        <div className="pixel-panel" style={{ background: "#ffe9c7" }}>
          <div className="panel-body" style={{ padding: 10 }}>
            <div className="pixel-label">Place hazard origin — tap the map</div>
          </div>
        </div>
      )}

      <ExposurePanel />
    </div>
  );
}