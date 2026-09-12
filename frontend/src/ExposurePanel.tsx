import { useStore } from "./store";
import type { ExposedAsset, PlannedAsset, SimResult } from "./types";

function bandBadge(band: string | undefined) {
  switch (band) {
    case "high":
      return ["red", "high exposure"];
    case "medium_high":
      return ["orange", "medium-high"];
    case "medium":
      return ["yellow", "medium"];
    case "low":
      return ["teal", "low"];
    case "flooded":
      return ["red", "flooded"];
    default:
      return ["green", "ok"];
  }
}

export function verdictForAsset(result: SimResult | null, asset: PlannedAsset): string {
  if (!result) return "";
  const entries: ExposedAsset[] =
    result.kind === "flood" ? result.exposure?.affected ?? [] : result.exposure?.exposed ?? [];
  const hit = entries.find((e) => String(e.id) === asset.id);
  if (!hit) return "outside estimated hazard";
  if (result.kind === "flood") return "inside the estimated flood extent";
  return bandBadge(hit.band)[1] + " exposure";
}

export default function ExposurePanel() {
  const result = useStore((s) => s.result);
  const mode = useStore((s) => s.mode);
  const placed = useStore((s) => s.placed);

  if (!result) return null;

  if (result.kind === "flood") {
    const { stats, dry, exposure } = result;
    return (
      <div className="panel-body" style={{ gap: 8 }}>
        <div className="chrome-title">Estimated Flood Extent</div>
        {dry ? (
          <div className="mini-note">
            This origin + rise is <b>hypothetical only</b> — the water surface is below the source cell, so nothing
            floods. Increase the rise or move the origin.
          </div>
        ) : (
          <>
            <div className="stat-grid">
              <div className="stat-box">
                <div className="num">{stats.area_km2.toFixed(1)}</div>
                <div className="lbl">km² estimated</div>
              </div>
              <div className="stat-box">
                <div className="num">{stats.percent_of_cells.toFixed(0)}%</div>
                <div className="lbl">of grid cells</div>
              </div>
              <div className="stat-box">
                <div className="num">{stats.water_surface_m.toFixed(0)}m</div>
                <div className="lbl">water surface</div>
              </div>
              <div className="stat-box">
                <div className="num">{(stats.max_depth_m ?? 0).toFixed(1)}m</div>
                <div className="lbl">max modelled depth</div>
              </div>
              <div className="stat-box">
                <div className="num">{exposure ? Object.keys(exposure.assets).length : 0}</div>
                <div className="lbl">asset types modelled</div>
              </div>
            </div>
            {mode === "new" && placed.length > 0 && (
              <PlannedVerdicts result={result} />
            )}
          </>
        )}
      </div>
    );
  }

  // earthquake
  const { bands, area_km2, radii_km } = result;
  const footprintKm2 = Object.values(area_km2).reduce((a, b) => a + b, 0);
  const radiiNote =
    radii_km && Object.keys(radii_km).length > 0 ? (
      <div className="mini-note">
        Estimated band reach: ~{radii_km.high ?? 0} km (high) · ~{radii_km.medium_high ?? 0} km
        (medium-high) · ~{radii_km.medium ?? 0} km (medium) from the epicenter. Scenario-based
        estimate, not a forecast.
      </div>
    ) : null;
  return (
    <div className="panel-body" style={{ gap: 8 }}>
      <div className="chrome-title">Estimated Shaking Intensity</div>
      <div className="stat-grid">
        <div className="stat-box">
          <div className="num">{footprintKm2.toFixed(1)}</div>
          <div className="lbl">km² estimated footprint</div>
        </div>
        <div className="stat-box">
          <div className="num">{bands.length}</div>
          <div className="lbl">intensity bands</div>
        </div>
      </div>
      <div className="legend-row">
        <span className="swatch" style={{ background: "#E34B4B" }} />
        <span>high · {area_km2.high?.toFixed(1)} km²</span>
        <span className="swatch" style={{ background: "#E59B45" }} />
        <span>medium-high · {area_km2.medium_high?.toFixed(1)} km²</span>
        <span className="swatch" style={{ background: "#E6C66A" }} />
        <span>medium · {area_km2.medium?.toFixed(1)} km²</span>
      </div>
      {radiiNote}
      {mode === "new" && placed.length > 0 && <PlannedVerdicts result={result} />}
    </div>
  );
}

function PlannedVerdicts({ result }: { result: SimResult }) {
  const placed = useStore((s) => s.placed);
  const runCount = useStore((s) => s.runCount);
  const exposed: ExposedAsset[] =
    result.kind === "flood" ? result.exposure?.affected ?? [] : result.exposure?.exposed ?? [];
  const byId = new Map(placed.map((a) => [a.id, a]));
  const rows = exposed
    .map((e) => {
      const asset = byId.get(String(e.id));
      if (!asset) return null;
      const [cls, label] = bandBadge(e.band);
      return { asset, cls, label };
    })
    .filter((r): r is NonNullable<typeof r> => Boolean(r));

  const atRisk = rows.filter((r) => r.cls === "red" || r.cls === "orange" || r.cls === "yellow").length;

  if (rows.length === 0) {
    return (
      <div className="mini-note">
        Your proposed facilities are outside the estimated hazard footprint in this scenario.
      </div>
    );
  }

  return (
    <div>
      <div className="chrome-title">Proposed Facilities · scenario {runCount}</div>
      {atRisk > 0 ? (
        <div className="result-badge warn" style={{ margin: "6px 0" }}>
          {atRisk} facility{atRisk > 1 ? "ies" : "y"} in estimated higher-risk zones
        </div>
      ) : (
        <div className="result-badge good" style={{ margin: "6px 0" }}>
          no facilities in estimated hazard
        </div>
      )}
      {rows.map((r) => (
        <div className="expo-row" key={r.asset.id} style={r.cls === "red" ? { background: "#ffe3dc" } : undefined}>
          <span className={`badge ${r.cls}`}>{r.cls === "red" ? "!" : r.cls}</span>
          <span className="e-name" style={{ textTransform: "capitalize" }}>
            {r.asset.type.replace("_", " ")}
          </span>
          <span className="e-kind">{r.label}</span>
        </div>
      ))}
      <div className="mini-note" style={{ marginTop: 6 }}>
        Scenario-based estimate — not a forecast. Move facilities and run again to compare.
      </div>
    </div>
  );
}