export interface MapGeometry {
  /** Neutral-band inset in px. */
  inset: number;
  /** Corner radius of the gray inset rect, clamped and inset-adjusted. */
  radius: number;
}

/**
 * Pure geometry for the displacement map. The radius clamp matters:
 * `rounded-full` elements compute to a 9999px border-radius, which must be
 * capped at half the smaller side before the inset adjustment.
 */
export function mapGeometry(
  w: number,
  h: number,
  radius: number,
  border: number,
): MapGeometry {
  const inset = border * Math.min(w, h);
  const clamped = Math.min(radius, w / 2, h / 2);
  return { inset, radius: Math.max(clamped - inset, 2) };
}

/**
 * Draw the gradient-difference displacement map: a red left→right ramp
 * encodes X displacement, a blue top→bottom ramp encodes Y ("difference"
 * keeps both since the channels are disjoint). A blurred, inset 50%-gray
 * rounded rect neutralizes the interior, confining refraction to an edge
 * band whose curvature is set by the blur radius.
 */
export function drawMap(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  geometry: MapGeometry,
  mapBlur: number,
): void {
  const gx = ctx.createLinearGradient(0, 0, w, 0);
  gx.addColorStop(0, "rgb(0,0,0)");
  gx.addColorStop(1, "rgb(255,0,0)");
  ctx.fillStyle = gx;
  ctx.fillRect(0, 0, w, h);

  const gy = ctx.createLinearGradient(0, 0, 0, h);
  gy.addColorStop(0, "rgb(0,0,0)");
  gy.addColorStop(1, "rgb(0,0,255)");
  ctx.globalCompositeOperation = "difference";
  ctx.fillStyle = gy;
  ctx.fillRect(0, 0, w, h);

  ctx.globalCompositeOperation = "source-over";
  ctx.filter = `blur(${mapBlur}px)`;
  ctx.fillStyle = "rgba(128,128,128,0.93)";
  ctx.beginPath();
  ctx.roundRect(
    geometry.inset,
    geometry.inset,
    w - geometry.inset * 2,
    h - geometry.inset * 2,
    geometry.radius,
  );
  ctx.fill();
  ctx.filter = "none";
}

export interface MapUrl {
  url: string;
  revoke(): void;
}

/**
 * Render the map and hand back a `blob:` object URL (cheaper than a base64
 * data URL: no 1.33× string copy per regeneration, and revocable). Falls
 * back to a data URL where `toBlob` is unavailable. Requires
 * `img-src blob:` (or `data:` for the fallback) in any CSP.
 */
export async function createMapUrl(
  w: number,
  h: number,
  radius: number,
  border: number,
  mapBlur: number,
): Promise<MapUrl> {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("liquid-glass: 2d canvas unavailable");

  drawMap(ctx, w, h, mapGeometry(w, h, radius, border), mapBlur);

  const blob = await new Promise<Blob | null>((resolve) => {
    if (typeof canvas.toBlob === "function") canvas.toBlob(resolve);
    else resolve(null);
  });
  if (blob) {
    const url = URL.createObjectURL(blob);
    return { url, revoke: () => URL.revokeObjectURL(url) };
  }
  return { url: canvas.toDataURL(), revoke: () => {} };
}
