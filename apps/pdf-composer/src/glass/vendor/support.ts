let cached: boolean | null = null;

/**
 * True where `backdrop-filter: url(#…)` actually refracts — Chromium only.
 * Safari and Firefox parse the value but silently no-op, so they are
 * excluded by user agent. SSR-safe: returns false without a DOM.
 */
export function isSupported(): boolean {
  if (typeof window === "undefined" || typeof document === "undefined") return false;
  if (cached !== null) return cached;

  const ua = navigator.userAgent;
  const isSafari = /Safari/.test(ua) && !/Chrome|Chromium|Edg/.test(ua);
  const isFirefox = /Firefox/.test(ua);
  if (isSafari || isFirefox) return (cached = false);
  if (typeof CSS === "undefined" || !CSS.supports("backdrop-filter", "url(#lg)")) {
    return (cached = false);
  }
  try {
    // Canvas readback must work for displacement-map generation.
    const c = document.createElement("canvas");
    c.width = c.height = 4;
    const ctx = c.getContext("2d");
    if (!ctx) return (cached = false);
    ctx.getImageData(0, 0, 1, 1);
    return (cached = true);
  } catch {
    return (cached = false);
  }
}

/** Test hook: reset the memoized detection result. */
export function resetSupportCache(): void {
  cached = null;
}
