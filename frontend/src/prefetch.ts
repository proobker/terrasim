// Forced tile preload: walks the slippy-map tiles over a city's area and pulls
// them into the browser HTTP cache before the player starts moving the camera.
// maplibre then gets each tile from cache in a few ms instead of a round trip
// to S3/Esri mid-pan — which is when draped imagery used to arrive late and
// leave bare, see-through terrain tiles behind.

type Bounds = [number, number, number, number];

export interface TileSet {
  template: string;
  bounds: Bounds;
  minzoom: number;
  maxzoom: number;
}

function lngToX(lng: number, z: number): number {
  return Math.floor(((lng + 180) / 360) * 2 ** z);
}

function latToY(lat: number, z: number): number {
  const r = (lat * Math.PI) / 180;
  return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z);
}

export function padBounds(b: Bounds, frac: number): Bounds {
  const dx = (b[2] - b[0]) * frac;
  const dy = (b[3] - b[1]) * frac;
  return [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy];
}

export function tileUrls({ template, bounds, minzoom, maxzoom }: TileSet): string[] {
  const urls: string[] = [];
  for (let z = minzoom; z <= maxzoom; z++) {
    const x0 = lngToX(bounds[0], z);
    const x1 = lngToX(bounds[2], z);
    const y0 = latToY(bounds[3], z);
    const y1 = latToY(bounds[1], z);
    for (let x = x0; x <= x1; x++) {
      for (let y = y0; y <= y1; y++) {
        urls.push(
          template.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y)),
        );
      }
    }
  }
  return urls;
}

/**
 * Fetch `urls` with bounded concurrency. Failures are ignored (maplibre will
 * retry the tile itself). Resolves when every request settles or `signal`
 * aborts; `onProgress` reports the settled fraction.
 */
export async function prefetch(
  urls: string[],
  {
    concurrency = 8,
    signal,
    onProgress,
  }: { concurrency?: number; signal?: AbortSignal; onProgress?: (done: number) => void } = {},
): Promise<void> {
  let next = 0;
  let settled = 0;
  const worker = async () => {
    while (next < urls.length && !signal?.aborted) {
      const url = urls[next++];
      try {
        const res = await fetch(url, { signal });
        // Drain the body so the cache entry is committed, not left half-read.
        await res.arrayBuffer();
      } catch {
        // tile server hiccup or abort; the map requests it again on demand
      }
      settled++;
      onProgress?.(settled / urls.length);
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, urls.length) }, worker));
}
