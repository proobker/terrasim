export type Sprite = { width: number; height: number; data: Uint8ClampedArray };

type Draw = (g: CanvasRenderingContext2D, px: number) => void;

const PX = 1;

function sprite(size: number, draw: Draw): Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = size * PX;
  canvas.height = size * PX;
  const g = canvas.getContext("2d")!;
  draw(g, PX);
  const image = g.getImageData(0, 0, canvas.width, canvas.height);
  return { width: canvas.width, height: canvas.height, data: image.data };
}

const rect = (
  g: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  color: string,
) => {
  g.fillStyle = color;
  g.fillRect(x * PX, y * PX, w * PX, h * PX);
};

function house(
  g: CanvasRenderingContext2D,
  x: number,
  y: number,
  body: string,
  roof: string,
) {
  rect(g, x, y, 4, 4, body);
  rect(g, x + 1, y - 2, 2, 2, roof);
  rect(g, x + 1, y + 2, 2, 2, "#1c2b24");
}

function cross(
  g: CanvasRenderingContext2D,
  x: number,
  y: number,
  color: string,
  background = "white",
) {
  rect(g, x, y, 4, 4, background);
  rect(g, x + 1, y, 2, 4, color);
  rect(g, x, y + 1, 4, 2, color);
}

const ICONS: Record<string, () => Sprite> = {
  building: () =>
    sprite(16, (g) => {
      rect(g, 0, 8, 12, 8, "#3a4d43");
      rect(g, 2, 6, 8, 4, "#4d6457");
      rect(g, 4, 2, 4, 4, "#5f7a6a");
      rect(g, 8, 4, 2, 2, "#9db8a8");
      rect(g, 0, 10, 12, 6, "#314137");
    }),
  hospital: () =>
    sprite(16, (g) => {
      rect(g, 0, 2, 16, 12, "#314137");
      cross(g, 2, 4, "#E34B4B");
      rect(g, 10, 4, 4, 8, "#4d6457");
      rect(g, 11, 5, 2, 2, "#9db8a8");
      rect(g, 11, 9, 2, 2, "#9db8a8");
      rect(g, 0, 14, 16, 2, "#24332b");
    }),
  clinic: () =>
    sprite(16, (g) => {
      rect(g, 0, 4, 16, 10, "#314137");
      cross(g, 6, 6, "#43C7D8");
      rect(g, 0, 2, 16, 2, "#3a4d43");
    }),
  school: () =>
    sprite(16, (g) => {
      rect(g, 0, 6, 16, 8, "#44594d");
      rect(g, 2, 3, 12, 3, "#5f7a6a");
      rect(g, 14, 0, 1, 3, "#314137");
      rect(g, 14, 1, 3, 1, "#E6C66A"); // flag
      rect(g, 2, 9, 4, 5, "#9db8a8");
      rect(g, 10, 9, 4, 5, "#9db8a8");
      rect(g, 0, 14, 16, 2, "#24332b");
    }),
  fire_station: () =>
    sprite(16, (g) => {
      rect(g, 0, 4, 16, 10, "#57222a");
      rect(g, 2, 12, 12, 2, "#E34B4B");
      rect(g, 2, 2, 12, 2, "#314137");
      rect(g, 3, 5, 3, 5, "#ffd9a0");
      rect(g, 10, 5, 3, 5, "#ffd9a0");
    }),
  police: () =>
    sprite(16, (g) => {
      rect(g, 0, 6, 16, 8, "#2a3f7a");
      rect(g, 0, 4, 16, 2, "#1c2b63");
      rect(g, 6, 2, 4, 2, "#E6C66A");
      rect(g, 4, 9, 8, 2, "#E6C66A");
      rect(g, 1, 12, 6, 2, "#0f1d3a");
      rect(g, 9, 12, 6, 2, "#0f1d3a");
    }),
  shelter: () =>
    sprite(16, (g) => {
      house(g, 2, 8, "#2f6b44", "#55B86A");
      rect(g, 8, 10, 3, 3, "#233c2c");
      rect(g, 11, 12, 4, 1, "#314137");
      rect(g, 0, 14, 16, 2, "#24332b");
    }),
  housing: () =>
    sprite(16, (g) => {
      house(g, 1, 9, "#8a745c", "#B08a5f");
      house(g, 9, 9, "#8a745c", "#B08a5f");
      rect(g, 0, 13, 16, 3, "#314137");
    }),
  epicenter: () =>
    sprite(16, (g) => {
      rect(g, 4, 2, 8, 2, "#E59B45");
      rect(g, 2, 4, 12, 8, "#E59B45");
      rect(g, 4, 4, 8, 8, "#E34B4B");
      rect(g, 6, 6, 4, 4, "#FFE9C7");
    }),
  source: () =>
    sprite(16, (g) => {
      rect(g, 5, 1, 6, 3, "#43C7D8");
      rect(g, 4, 4, 8, 4, "#43C7D8");
      rect(g, 3, 8, 10, 4, "#43C7D8");
      rect(g, 2, 12, 12, 2, "#2fa8ba");
      rect(g, 0, 14, 16, 2, "#1c8a99");
    }),
  downtown: () =>
    sprite(16, (g) => {
      rect(g, 1, 2, 12, 8, "#44594d");
      rect(g, 4, 6, 6, 4, "#E6C66A");
      rect(g, 4, 10, 8, 3, "#314137");
      rect(g, 5, 6, 2, 2, "#314137");
    }),
  pin: () =>
    sprite(16, (g) => {
      rect(g, 3, 0, 10, 4, "#E6C66A");
      rect(g, 4, 4, 8, 2, "#E6C66A");
      rect(g, 6, 6, 4, 6, "#E6C66A");
      rect(g, 2, 12, 12, 4, "#B08a5f");
    }),
  flow: () =>
    sprite(16, (g) => {
      const c = "#6FE3F0";
      rect(g, 1, 6, 5, 4, c);
      rect(g, 6, 5, 6, 2, c);
      rect(g, 8, 3, 5, 2, c);
      rect(g, 10, 1, 4, 2, c);
      rect(g, 6, 9, 6, 2, c);
      rect(g, 8, 11, 5, 2, c);
      rect(g, 10, 13, 4, 2, c);
    }),
};

const ICON_ATLAS: Record<string, string> = {
  building: "ts-building",
  hospital: "ts-hospital",
  clinic: "ts-clinic",
  school: "ts-school",
  fire_station: "ts-fire",
  police: "ts-police",
  shelter: "ts-shelter",
  housing: "ts-housing",
  higher_ed: "ts-school",
  epicenter: "ts-epicenter",
  source: "ts-source",
  flow: "ts-flow",
};

export function atlasDefinitions(): Record<string, Sprite> {
  const entries: [string, Sprite][] = Object.entries(ICONS).map(
    ([key, draw]) => [ICON_ATLAS[key] ?? `ts-${key}`, draw()],
  );
  return Object.fromEntries(entries);
}

export function iconForType(type: string | undefined): string {
  const key = (type ?? "").toLowerCase();
  if (key in ICON_ATLAS) return ICON_ATLAS[key];
  if (
    key.includes("school") ||
    key.includes("college") ||
    key.includes("university")
  )
    return "ts-school";
  if (key.includes("clinic") || key.includes("doctor")) return "ts-clinic";
  if (key.includes("hospital")) return "ts-hospital";
  if (
    key.includes("health") ||
    key.includes("pharmacy") ||
    key.includes("care")
  )
    return "ts-clinic";
  if (key.includes("fire")) return "ts-fire";
  if (key.includes("police")) return "ts-police";
  if (key.includes("shelter") || key.includes("community")) return "ts-shelter";
  return "ts-building";
}

function drawKeyFor(type: string): string {
  const key = type.toLowerCase();
  if (key in ICONS) return key;
  if (key === "higher_ed") return "school";
  if (
    key.includes("school") ||
    key.includes("college") ||
    key.includes("university")
  )
    return "school";
  if (key.includes("clinic") || key.includes("doctor")) return "clinic";
  if (key.includes("hospital")) return "hospital";
  if (key.includes("fire")) return "fire_station";
  if (key.includes("police")) return "police";
  if (key.includes("shelter") || key.includes("community")) return "shelter";
  return "building";
}

/** Render a friendly icon name to a scaled pixel canvas for UI previews. */
export function previewCanvas(
  type: string,
  size = 36,
  padding = 2,
): HTMLCanvasElement {
  const sprite = ICONS[drawKeyFor(type)]();
  const tmp = document.createElement("canvas");
  tmp.width = sprite.width;
  tmp.height = sprite.height;
  const tg = tmp.getContext("2d")!;
  tg.putImageData(
    new ImageData(
      new Uint8ClampedArray(sprite.data),
      sprite.width,
      sprite.height,
    ),
    0,
    0,
  );

  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  drawSpriteScaled(canvas, tmp, padding, size - padding * 2);
  return canvas;
}

/** Draw the sprite for an icon type into an existing canvas element. */
export function drawPreviewInto(
  type: string,
  canvas: HTMLCanvasElement,
  padding = 2,
): void {
  const sprite = ICONS[drawKeyFor(type)]();
  const tmp = document.createElement("canvas");
  tmp.width = sprite.width;
  tmp.height = sprite.height;
  tmp
    .getContext("2d")!
    .putImageData(
      new ImageData(
        new Uint8ClampedArray(sprite.data),
        sprite.width,
        sprite.height,
      ),
      0,
      0,
    );
  const edge = Math.min(canvas.width, canvas.height);
  drawSpriteScaled(canvas, tmp, padding, edge - padding * 2);
}

function drawSpriteScaled(
  target: HTMLCanvasElement,
  src: HTMLCanvasElement,
  x: number,
  size: number,
): void {
  const g = target.getContext("2d")!;
  g.clearRect(0, 0, target.width, target.height);
  g.imageSmoothingEnabled = false;
  g.drawImage(src, x, x, size, size);
}
