import { isSupported } from "./support.js";
import type { QualityOptions, QualityTier } from "./types.js";

const MQ = {
  reducedTransparency: "(prefers-reduced-transparency: reduce)",
  contrastMore: "(prefers-contrast: more)",
  reducedMotion: "(prefers-reduced-motion: reduce)",
  desktop: "(hover: hover) and (pointer: fine)",
} as const;

interface NavigatorExtras extends Navigator {
  deviceMemory?: number;
  connection?: {
    saveData?: boolean;
    addEventListener?: (type: "change", cb: () => void) => void;
    removeEventListener?: (type: "change", cb: () => void) => void;
  };
}

function matches(query: string): boolean {
  return window.matchMedia(query).matches;
}

/**
 * Resolve the rendering tier for the current environment.
 *
 * Gating order for `"auto"`: SSR → support (Chromium) → accessibility
 * preferences → Save-Data → desktop (`hover + fine pointer`) = high →
 * capable Android (deviceMemory/cores) = lite → off. Explicit
 * `"high"`/`"lite"` skip only the last two steps; support, accessibility,
 * and Save-Data remain hard gates.
 */
export function resolveQuality(opts: QualityOptions = {}): QualityTier {
  const { quality = "auto", allowLite = true, respectReducedMotion = true } = opts;

  if (quality === "off") return "off";
  if (typeof window === "undefined") return "off";
  if (!isSupported()) return "off";
  if (matches(MQ.reducedTransparency) || matches(MQ.contrastMore)) return "off";
  if (respectReducedMotion && matches(MQ.reducedMotion)) return "off";

  const nav = navigator as NavigatorExtras;
  if (nav.connection?.saveData === true) return "off";

  if (quality === "high" || quality === "lite") return quality;

  if (matches(MQ.desktop)) return "high";
  const capableMobile =
    allowLite && (nav.deviceMemory ?? 4) >= 4 && (nav.hardwareConcurrency ?? 4) >= 4;
  return capableMobile ? "lite" : "off";
}

/**
 * Watch every live input of {@link resolveQuality} (the four media queries
 * plus Save-Data) and invoke `cb` with the new tier whenever it changes.
 * Returns an unsubscribe function. SSR-safe no-op without a DOM.
 */
export function observeQuality(
  opts: QualityOptions,
  cb: (tier: QualityTier) => void,
): () => void {
  if (typeof window === "undefined") return () => {};

  let last = resolveQuality(opts);
  const emit = () => {
    const tier = resolveQuality(opts);
    if (tier !== last) {
      last = tier;
      cb(tier);
    }
  };

  const mqls = Object.values(MQ).map((q) => window.matchMedia(q));
  for (const mql of mqls) mql.addEventListener("change", emit);
  const connection = (navigator as NavigatorExtras).connection;
  connection?.addEventListener?.("change", emit);

  return () => {
    for (const mql of mqls) mql.removeEventListener("change", emit);
    connection?.removeEventListener?.("change", emit);
  };
}
