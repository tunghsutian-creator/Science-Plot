import { useEffect, useRef } from 'react';
import type { PointerEvent, ReactNode } from 'react';
import { liquidGlass } from '../glass/vendor/engine';
import { observeQuality } from '../glass/vendor/tiers';

const refraction = { quality: 'high' as const, scale: -48, chroma: 1.5, border: 0.07, mapBlur: 10, passes: 1 as const };

/** One local SVG engine on small surfaces; foreground content is never filtered. */
export function GlassSurface({ children, className = '', refract = false }: {
  children: ReactNode; className?: string; refract?: boolean;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const point = useRef({ x: 50, y: 0 });
  const reducedMotion = useRef(false);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => { reducedMotion.current = media.matches; };
    update(); media.addEventListener('change', update);
    return () => { media.removeEventListener('change', update); cancelAnimationFrame(frame.current); };
  }, []);

  useEffect(() => {
    const element = backdrop.current;
    if (!refract || !element) return;
    let instance = liquidGlass(element, refraction);
    const stop = observeQuality(refraction, () => {
      instance.destroy(); instance = liquidGlass(element, refraction);
    });
    return () => { stop(); instance.destroy(); };
  }, [refract]);

  function highlight(event: PointerEvent<HTMLDivElement>) {
    if (reducedMotion.current) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    point.current = { x: (event.clientX - bounds.left) / bounds.width * 100, y: (event.clientY - bounds.top) / bounds.height * 100 };
    if (!frame.current) frame.current = requestAnimationFrame(() => {
      surface.current?.style.setProperty('--glass-pointer-x', `${point.current.x}%`);
      surface.current?.style.setProperty('--glass-pointer-y', `${point.current.y}%`);
      frame.current = 0;
    });
  }

  return <div ref={surface} className={`glass-surface ${className}`} onPointerMove={highlight}>
    <div ref={backdrop} className="glass-backdrop" aria-hidden="true" />
    <div className="glass-foreground">{children}</div>
  </div>;
}
