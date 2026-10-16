export type QualityTier = "high" | "lite" | "off";

export interface QualityOptions {
  /**
   * Rendering tier. `"auto"` (default) resolves per device: full refraction
   * on desktop Chromium, a cheaper single-pass variant on capable Android,
   * `"off"` everywhere else. Explicit `"high"`/`"lite"` skip the device
   * heuristics but still respect the support check, accessibility
   * preferences, and Save-Data. `"off"` disables the engine entirely.
   */
  quality?: "auto" | QualityTier;
  /** Allow `"auto"` to resolve to `"lite"` on capable mobile Chromium. Default `true`. */
  allowLite?: boolean;
  /** Treat `prefers-reduced-motion: reduce` as a hard off-switch. Default `true`. */
  respectReducedMotion?: boolean;
}

export interface LiquidGlassOptions extends QualityOptions {
  /** Displacement strength; negative values create the magnifying bulge. Default `-112`. */
  scale?: number;
  /** Per-channel scale stagger producing the prism fringe; `0` disables it. Default `6`. */
  chroma?: number;
  /** Neutral inset as a fraction of the smaller side. Default `0.07`. */
  border?: number;
  /** Edge-curvature softness (px) of the map's gray inset. Default `12`. */
  mapBlur?: number;
  /** Corner radius override (px); by default reads the element's border-radius. */
  radius?: number | null;
  /** Displacement passes. Defaults per tier: high = 3 (with fringe), lite = 1. */
  passes?: 1 | 3;
  /** Overrides applied on the lite tier. Defaults: `scale * 0.6`, `mapBlur * 0.75`. */
  liteOverrides?: { scale?: number; mapBlur?: number };
}

export interface LiquidGlassInstance {
  /** Tier resolved at init. `"off"` means the instance is a no-op. */
  tier: QualityTier;
  /** Force a displacement-map regeneration (e.g. after a programmatic size change). */
  refresh(): void;
  /** Tear down: observer, SVG filter, element attributes, object URLs. */
  destroy(): void;
}
