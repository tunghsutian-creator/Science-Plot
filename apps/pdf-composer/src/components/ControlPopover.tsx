import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

const focusable = 'button:not(:disabled),summary,a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])';

function restoreAnchorFocus(anchor: HTMLElement | null) {
  if (!anchor?.isConnected) return;
  const candidates = anchor.matches(focusable) ? [anchor] : Array.from(anchor.querySelectorAll<HTMLElement>(focusable));
  candidates.find((element) => element.getAttribute('aria-disabled') !== 'true' && element.getClientRects().length > 0)?.focus({ preventScroll: true });
}

/** Nonmodal, button-anchored settings. It never covers or blurs the workspace. */
export function AnchoredPanel({ anchor, id, title, onClose, className = '', children }: {
  anchor: HTMLElement | null; id?: string; title: string; onClose: () => void;
  className?: string; children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: 8, top: 8, maxHeight: 400 });
  useLayoutEffect(() => {
    const surface = panel.current;
    const place = () => {
      const origin = anchor?.getBoundingClientRect(), popup = panel.current?.getBoundingClientRect();
      if (!origin || !popup) return;
      const below = window.innerHeight - origin.bottom - 16, above = origin.top - 16;
      const useAbove = below < popup.height && above > below;
      const maxHeight = Math.max(80, useAbove ? above : below);
      const top = useAbove ? Math.max(8, origin.top - Math.min(popup.height, maxHeight) - 8) : origin.bottom + 8;
      const left = Math.max(8, Math.min(origin.left, window.innerWidth - popup.width - 8));
      setPosition((current) => current.left === left && current.top === top && current.maxHeight === maxHeight ? current : { left, top, maxHeight });
    };
    place();
    const observer = new ResizeObserver(place);
    if (panel.current) observer.observe(panel.current);
    window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    panel.current?.querySelector<HTMLElement>('button:not(:disabled),input,select,[tabindex="0"]')?.focus();
    return () => {
      observer.disconnect(); window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true);
      // Layout cleanup runs before the focused popup node is removed. Returning
      // focus here also covers Apply/Zoom choices, without stealing outside focus.
      if (surface?.contains(document.activeElement)) restoreAnchorFocus(anchor);
    };
  }, [anchor]);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !anchor?.contains(event.target) && !panel.current?.contains(event.target)) onClose();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); event.stopPropagation(); onClose(); restoreAnchorFocus(anchor);
    };
    document.addEventListener('pointerdown', outside, true); document.addEventListener('keydown', escape, true);
    return () => { document.removeEventListener('pointerdown', outside, true); document.removeEventListener('keydown', escape, true); };
  }, [anchor, onClose]);

  return <div ref={panel} id={id} role="dialog" aria-label={title} aria-modal="false"
    className={`control-popover ${className}`} style={position} onKeyDown={(event) => {
      if (!(event.target instanceof HTMLElement) || event.target.getAttribute('role') !== 'menuitemradio') return;
      const choices = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'));
      const index = choices.indexOf(event.target as HTMLButtonElement);
      const next = event.key === 'ArrowDown' ? (index + 1) % choices.length : event.key === 'ArrowUp' ? (index + choices.length - 1) % choices.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? choices.length - 1 : -1;
      if (next >= 0) { event.preventDefault(); choices[next]?.focus(); }
    }}>{children}</div>;
}

export function ControlPopover({ label, title, open, onOpenChange, disabled, className = '', children, trigger }: {
  label: string; title: string; open: boolean; onOpenChange: (open: boolean) => void;
  disabled?: boolean; className?: string; children: ReactNode; trigger: ReactNode;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);

  return <div className="control-popover-anchor">
    <button ref={button} type="button" className="toolbar-control" aria-label={label} title={title}
      aria-expanded={open} aria-controls={open ? id : undefined} aria-haspopup="dialog" disabled={disabled}
      onClick={() => onOpenChange(!open)} onKeyDown={(event) => {
        if (event.key === 'ArrowDown') { event.preventDefault(); onOpenChange(true); }
      }}>{trigger}</button>
    {open ? <AnchoredPanel anchor={button.current} id={id} title={title} className={className} onClose={() => onOpenChange(false)}>{children}</AnchoredPanel> : null}
  </div>;
}
