const SVG_NS = "http://www.w3.org/2000/svg";

let host: SVGSVGElement | null = null;
let defs: SVGDefsElement | null = null;
let filterCount = 0;
let uid = 0;

function ensureDefs(): SVGDefsElement {
  if (defs && host?.isConnected) return defs;
  host = document.createElementNS(SVG_NS, "svg");
  // width/height 0 keeps it renderable (display:none would break feImage).
  host.setAttribute("width", "0");
  host.setAttribute("height", "0");
  host.setAttribute("aria-hidden", "true");
  host.setAttribute("data-lg-host", "");
  host.style.position = "absolute";
  defs = document.createElementNS(SVG_NS, "defs");
  host.appendChild(defs);
  document.body.appendChild(host);
  return defs;
}

export interface FilterParts {
  id: string;
  feImage: SVGFEImageElement;
  /** Detach the filter; the shared host is removed with the last filter. */
  remove(): void;
}

/**
 * Build a displacement filter inside the shared singleton host.
 * `scales.length === 1` produces the cheap single-pass (lite) pipeline;
 * three scales produce the staggered per-channel passes recombined with
 * screen blends — the prism fringe at the rim.
 */
export function createFilter(scales: readonly number[]): FilterParts {
  const id = `lg-filter-${++uid}`;
  const filter = document.createElementNS(SVG_NS, "filter");
  filter.setAttribute("id", id);
  filter.setAttribute("x", "0");
  filter.setAttribute("y", "0");
  filter.setAttribute("width", "100%");
  filter.setAttribute("height", "100%");
  // Load-bearing: filters default to linearRGB, which re-maps the map's
  // neutral gray 128 to ~0.216 and injects a constant phantom displacement.
  filter.setAttribute("color-interpolation-filters", "sRGB");

  const feImage = document.createElementNS(SVG_NS, "feImage");
  feImage.setAttribute("x", "0");
  feImage.setAttribute("y", "0");
  feImage.setAttribute("result", "map");
  feImage.setAttribute("preserveAspectRatio", "none");
  filter.appendChild(feImage);

  if (scales.length === 1) {
    const disp = document.createElementNS(SVG_NS, "feDisplacementMap");
    disp.setAttribute("in", "SourceGraphic");
    disp.setAttribute("in2", "map");
    disp.setAttribute("scale", String(scales[0]));
    disp.setAttribute("xChannelSelector", "R");
    disp.setAttribute("yChannelSelector", "B");
    filter.appendChild(disp);
  } else {
    const keep = [
      "1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0",
      "0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0",
      "0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0",
    ];
    const channels: string[] = [];
    scales.forEach((scale, i) => {
      const disp = document.createElementNS(SVG_NS, "feDisplacementMap");
      disp.setAttribute("in", "SourceGraphic");
      disp.setAttribute("in2", "map");
      disp.setAttribute("scale", String(scale));
      disp.setAttribute("xChannelSelector", "R");
      disp.setAttribute("yChannelSelector", "B");
      disp.setAttribute("result", `d${i}`);
      filter.appendChild(disp);

      const cm = document.createElementNS(SVG_NS, "feColorMatrix");
      cm.setAttribute("in", `d${i}`);
      cm.setAttribute("type", "matrix");
      cm.setAttribute("values", keep[i]!);
      cm.setAttribute("result", `c${i}`);
      filter.appendChild(cm);
      channels.push(`c${i}`);
    });

    const blend1 = document.createElementNS(SVG_NS, "feBlend");
    blend1.setAttribute("in", channels[0]!);
    blend1.setAttribute("in2", channels[1]!);
    blend1.setAttribute("mode", "screen");
    blend1.setAttribute("result", "c01");
    filter.appendChild(blend1);

    const blend2 = document.createElementNS(SVG_NS, "feBlend");
    blend2.setAttribute("in", "c01");
    blend2.setAttribute("in2", channels[2]!);
    blend2.setAttribute("mode", "screen");
    filter.appendChild(blend2);
  }

  ensureDefs().appendChild(filter);
  filterCount++;

  let removed = false;
  return {
    id,
    feImage,
    remove() {
      if (removed) return;
      removed = true;
      filter.remove();
      if (--filterCount === 0) {
        host?.remove();
        host = null;
        defs = null;
      }
    },
  };
}
