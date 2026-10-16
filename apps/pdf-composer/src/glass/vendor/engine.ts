import { applyGlass, clearGlass } from "./apply.js";
import { createMapUrl } from "./map.js";
import { createFilter } from "./svg.js";
import { resolveQuality } from "./tiers.js";
import type { LiquidGlassInstance, LiquidGlassOptions } from "./types.js";

const DEFAULTS = {
  scale: -112,
  chroma: 6,
  border: 0.07,
  mapBlur: 12,
  radius: null as number | null,
};

const RESIZE_DEBOUNCE_MS = 120;

function resolveRadius(
  el: HTMLElement,
  w: number,
  h: number,
  override: number | null,
): number {
  if (override != null) return override;
  const raw = getComputedStyle(el).borderTopLeftRadius || "0px";
  const v = parseFloat(raw) || 0;
  return raw.trim().endsWith("%") ? (v / 100) * Math.min(w, h) : v;
}

const NOOP_INSTANCE: LiquidGlassInstance = {
  tier: "off",
  refresh() {},
  destroy() {},
};

/**
 * Apply liquid-glass refraction to an element.
 *
 * Headless: the engine only wires the SVG filter and sets the element
 * contract (`--lg-filter-url`, `data-lg-active`, `data-lg-quality`); the
 * `backdrop-filter` itself comes from your CSS (or the optional
 * styles.css). When the resolved tier is `"off"` this is a complete no-op —
 * your fallback styling stays untouched.
 */
export function liquidGlass(
  el: HTMLElement,
  opts: LiquidGlassOptions = {},
): LiquidGlassInstance {
  const resolved = resolveQuality(opts);
  if (resolved === "off") return NOOP_INSTANCE;
  const tier: "high" | "lite" = resolved;

  const o = { ...DEFAULTS, ...opts };
  const passes = opts.passes ?? (tier === "lite" ? 1 : 3);
  let scale = o.scale;
  let mapBlur = o.mapBlur;
  const chroma = passes === 1 ? 0 : o.chroma;
  if (tier === "lite") {
    scale = opts.liteOverrides?.scale ?? scale * 0.6;
    mapBlur = opts.liteOverrides?.mapBlur ?? mapBlur * 0.75;
  }

  const scales =
    passes === 1 ? [scale] : [scale, scale + chroma, scale + 2 * chroma];
  const parts = createFilter(scales);

  let destroyed = false;
  let applied = false;
  let generation = 0;
  let lastW = 0;
  let lastH = 0;
  let revokeCurrent: (() => void) | null = null;

  async function refresh(force: boolean): Promise<void> {
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    if (!w || !h) return;
    // Subpixel deltas from fractional layout/zoom don't warrant an
    // O(w*h) map regeneration.
    if (!force && Math.abs(w - lastW) < 1 && Math.abs(h - lastH) < 1) return;
    lastW = w;
    lastH = h;

    const gen = ++generation;
    const map = await createMapUrl(
      w,
      h,
      resolveRadius(el, w, h, o.radius),
      o.border,
      mapBlur,
    );
    // A newer regeneration or destroy() won the race — discard this map.
    if (destroyed || gen !== generation) {
      map.revoke();
      return;
    }
    revokeCurrent?.();
    revokeCurrent = map.revoke;
    parts.feImage.setAttribute("href", map.url);
    parts.feImage.setAttribute("width", String(w));
    parts.feImage.setAttribute("height", String(h));
    // The element contract goes live only once the first map is in place —
    // a filter with an empty feImage displaces against transparent black
    // and would visibly shear the backdrop.
    if (!applied) {
      applied = true;
      applyGlass(el, parts.id, tier);
    }
  }

  void refresh(true);

  let timer: ReturnType<typeof setTimeout> | null = null;
  const ro = new ResizeObserver(() => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void refresh(false), RESIZE_DEBOUNCE_MS);
  });
  ro.observe(el);

  return {
    tier,
    refresh: () => void refresh(true),
    destroy() {
      if (destroyed) return;
      destroyed = true;
      ro.disconnect();
      if (timer) clearTimeout(timer);
      parts.remove();
      revokeCurrent?.();
      revokeCurrent = null;
      clearGlass(el);
    },
  };
}
