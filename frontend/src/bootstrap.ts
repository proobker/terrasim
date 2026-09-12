import { useEffect } from "react";
import { api } from "./api";
import { useStore } from "./store";

export async function bootstrapCities(): Promise<void> {
  const store = useStore.getState();
  store.setBootState("loading");
  try {
    const cities = await api.cities();
    store.setCities(cities);
    store.setBootState("ready");
  } catch {
    store.setBootState("error");
  }
}

/** Fetch demo areas on mount; keep retrying while the backend is unreachable. */
export function useCityBootstrap(): void {
  useEffect(() => {
    void bootstrapCities();
    const interval = setInterval(() => {
      const s = useStore.getState();
      if (s.bootState === "error" && document.visibilityState === "visible") {
        void bootstrapCities();
      }
    }, 2500);
    const onFocus = () => {
      if (useStore.getState().bootState === "error") void bootstrapCities();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, []);
}