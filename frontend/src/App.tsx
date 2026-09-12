import { useMemo, useState } from "react";
import MapView from "./MapView";
import SidePanel from "./SidePanel";
import Topbar from "./Topbar";
import { bootstrapCities } from "./bootstrap";
import { api } from "./api";
import { useStore } from "./store";

function FacilityChip() {
  const detail = useStore((s) => s.facilityDetail);
  const setDetail = useStore((s) => s.setFacilityDetail);
  if (!detail) return null;
  return (
    <div className="pixel-panel facility-chip" onClick={() => setDetail(null)}>
      <div className="panel-body" style={{ padding: 10, gap: 2 }}>
        <div className="pixel-label">Selected facility</div>
        <div className="dialog-text" style={{ fontWeight: 700, textTransform: "capitalize" }}>
          {detail.name || "(unnamed)"} <em style={{ fontSize: 12 }}>{detail.type}</em>
        </div>
        <div className="mini-note">Scenario-based exposure shows in the panel. Click to dismiss.</div>
      </div>
    </div>
  );
}

function ErrorToast() {
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  if (!error) return null;
  return (
    <div className="toast-error" onClick={() => setError(null)}>
      {error}
    </div>
  );
}

function MapHint() {
  const mode = useStore((s) => s.mode);
  const hazard = useStore((s) => s.hazard);
  const pendingAsset = useStore((s) => s.pendingAsset);
  const pickingOrigin = useStore((s) => s.pickingOrigin);
  const source = useStore((s) => s.source);
  const selectedAssetId = useStore((s) => s.selectedAssetId);
  const selectedRiverId = useStore((s) => s.selectedRiverId);
  const result = useStore((s) => s.result);

  const text = useMemo(() => {
    if (pickingOrigin) return "Tap the map to place the hazard origin";
    if (pendingAsset) return "Tap the map to place the facility";
    if (mode === "new") {
      if (hazard === "flood" && selectedRiverId) return "River selected · set the rise and run the scenario";
      if (selectedAssetId) return "Tap the map to move the selected facility";
      if (!source) return "Select a facility tile, then tap the map to place it";
      return "Tap a facility to reposition · Run a scenario to test";
    }
    if (hazard === "flood" && selectedRiverId) return "River selected · set the rise and run the scenario";
    if (!source) return hazard === "flood" ? "Tap the map to set the flood origin" : "Tap the map to set the epicenter";
    if (!result) return "Set parameters, then run the scenario";
    return "Scenario complete · toggle layers or run again";
  }, [mode, hazard, pendingAsset, pickingOrigin, source, selectedAssetId, selectedRiverId, result]);

  return <div className="map-hint">{text}</div>;
}

function BootScreen() {
  const bootState = useStore((s) => s.bootState);
  const cities = useStore((s) => s.cities);

  return (
    <div className="boot-screen">
      <div className="pixel-panel boot-card">
        <div>
          <div className="logo">
            TERRA<span className="dot">S</span>IM
          </div>
          {bootState === "ready" && cities.length === 0 ? (
            <>
              <div className="tagline" style={{ marginTop: 10 }}>
                no demo areas on the server at {api.base}
              </div>
              <div className="mini-note">
                Build bundles with <code>scripts/fetch_data.py --all</code>, then retry.
              </div>
              <button className="pixel-btn primary" style={{ marginTop: 14 }} onClick={() => void bootstrapCities()}>
                Retry
              </button>
            </>
          ) : bootState === "error" ? (
            <>
              <div className="tagline" style={{ marginTop: 10 }}>
                can't reach the sim engine at {api.base}
              </div>
              <div className="mini-note">
                Start it with <code>uv run uvicorn app.main:app --port 8000</code> in <code>backend/</code>.
              </div>
              <button className="pixel-btn primary" style={{ marginTop: 14 }} onClick={() => void bootstrapCities()}>
                Retry
              </button>
            </>
          ) : (
            <>
              <div className="tagline" style={{ marginTop: 10 }}>
                connecting to the sim engine at {api.base}…
              </div>
              <div className="pixel-bar">
                <div style={{ width: "70%" }} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [mapReady, setMapReady] = useState(false);
  const city = useStore((s) => s.city);
  const cities = useStore((s) => s.cities);
  const running = useStore((s) => s.running);

  const booting = !mapReady || cities.length === 0;

  return (
    <div className="app" style={running ? { cursor: "progress" } : undefined}>
      <Topbar />
      <div className="map-frame">
        <MapView onReady={() => setMapReady(true)} />
        {booting && <BootScreen />}
        {!booting && <MapHint />}
        <SidePanel />
        <FacilityChip />
        <ErrorToast />
      </div>
      {city && (
        <footer className="tagline" style={{ textAlign: "center", padding: "6px 0 10px" }}>
          {city.name} · estimated scenario layers, not forecasts · terrain SRTM-derived · data © OpenStreetMap contributors
        </footer>
      )}
    </div>
  );
}