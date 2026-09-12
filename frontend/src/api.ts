import type {
  CityInfo,
  EarthquakeScenario,
  FeatureCollection,
  FloodScenario,
  LayerKind,
  SimResult,
  SuitabilityResult,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API ${res.status}: ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export const api = {
  base: API_BASE,

  async health(): Promise<{ status: string; version: string; cities: number }> {
    return request("/api/health");
  },

  async cities(): Promise<CityInfo[]> {
    const data = await request<{ cities: CityInfo[] }>("/api/cities");
    return data.cities;
  },

  async layer(cityId: string, kind: LayerKind): Promise<FeatureCollection | null> {
    try {
      return await request(`/api/cities/${cityId}/layers/${kind}`);
    } catch {
      return null;
    }
  },

  async flood(scenario: FloodScenario): Promise<SimResult> {
    return request("/api/simulate/flood", { method: "POST", body: JSON.stringify(scenario) });
  },

  async quake(scenario: EarthquakeScenario): Promise<SimResult> {
    return request("/api/simulate/earthquake", { method: "POST", body: JSON.stringify(scenario) });
  },

  async suitability(cityId: string): Promise<SuitabilityResult> {
    return request(`/api/cities/${cityId}/suitability`, { method: "POST", body: JSON.stringify({ city_id: cityId }) });
  },
};