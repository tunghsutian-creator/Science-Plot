import type { QualityTier } from "./types.js";

/**
 * The element contract (public API, frozen at v0.1.0):
 *   --lg-filter-url   custom property holding `url(#lg-filter-…)`
 *   data-lg-active    present while a filter is wired
 *   data-lg-quality   resolved tier, for per-tier styling
 *
 * The engine never writes `backdrop-filter` inline — consumers apply it in
 * CSS (their own rules or the optional styles.css), so media-query
 * fallbacks and theme tokens keep working. Property and attribute are set
 * in the same synchronous block: an attribute without the property would
 * make `var(--lg-filter-url)` invalid-at-computed-value and momentarily
 * disable the element's entire backdrop-filter.
 */
export function applyGlass(
  el: HTMLElement,
  filterId: string,
  tier: Exclude<QualityTier, "off">,
): void {
  el.style.setProperty("--lg-filter-url", `url(#${filterId})`);
  el.setAttribute("data-lg-active", "");
  el.setAttribute("data-lg-quality", tier);
}

export function clearGlass(el: HTMLElement): void {
  el.style.removeProperty("--lg-filter-url");
  el.removeAttribute("data-lg-active");
  el.removeAttribute("data-lg-quality");
}
