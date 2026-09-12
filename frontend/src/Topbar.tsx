import { useEffect } from "react";
import { api } from "./api";
import { useStore } from "./store";
import type { CityInfo } from "./types";

export default function Topbar() {
  const cities = useStore((s) => s.cities);
  const setCities = useStore((s) => s.setCities);
  const city = useStore((s) => s.city);
  const selectCity = useStore((s) => s.selectCity);
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);

  useEffect(() => {
    void api.cities().then(setCities).catch(() => setCities([]));
  }, [setCities]);

  useEffect(() => {
    if (!city && cities.length > 0) {
      const preferred = cities.find((c: CityInfo) => c.mode === mode) ?? cities[0];
      selectCity(preferred);
    }
  }, [cities, city, mode, selectCity]);

  return (
    <header className="topbar">
      <div>
        <div className="logo">
          TERRA<span className="dot">S</span>IM
        </div>
        <div className="tagline">Building Resilient Areas for Climate &amp; Emergencies</div>
      </div>

      <div className="topbar-space" />

      <div className="mode-switch">
        <button className="pixel-tab" data-active={mode === "existing"} onClick={() => setMode("existing")}>
          Existing City
        </button>
        <button className="pixel-tab" data-active={mode === "new"} onClick={() => setMode("new")}>
          New City
        </button>
      </div>

      <select
        className="pixel-select"
        style={{ width: 200 }}
        value={city?.id ?? ""}
        onChange={(e) => {
          const next = cities.find((c: CityInfo) => c.id === e.target.value);
          if (next) {
            selectCity(next);
            setMode(next.mode === "new" ? "new" : "existing");
          }
        }}
      >
        {cities.length === 0 && <option>no cities on server</option>}
        {cities.map((c: CityInfo) => (
          <option key={c.id} value={c.id}>
            {c.name} · {c.mode === "new" ? "planned" : "existing"}
          </option>
        ))}
      </select>
    </header>
  );
}