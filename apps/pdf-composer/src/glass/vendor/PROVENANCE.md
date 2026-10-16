# Pinned liquid-glass engine

Source: https://github.com/xcyberpunkx0/liquid-glass

Exact revision: `b1313491cd29bc7a3cb66284324b01bdc3f41313`.
Upstream package metadata names `@xcyberpunkx0/liquid-glass`, version `0.1.0`.
The official npm registry returned HTTP 404 for this package during verification
on 2026-10-16, so no unverified npm release or Git installation hook is used.

`apply.ts`, `engine.ts`, `map.ts`, `support.ts`, `svg.ts`, `tiers.ts`, `types.ts`
are copied from upstream `src/core/` at that revision. The sole adaptation is
`engine.ts`'s never-reassigned `chroma` binding changed from `let` to `const` to
meet the host lint rule; runtime behavior is unchanged. All other source files
are byte-identical. `LICENSE` is
copied unchanged and retains both upstream copyright notices. No upstream
repository build, test, install, demo, or publishing script was run.

The application-owned adapter is `../../components/GlassSurface.tsx`. It uses
only this single engine, a single displacement pass and small control groups.
It observes upstream quality/accessibility preferences, tears down maps and
observers, and keeps pointer highlighting in animation frames. The wide source
tray has CSS glass styling only; it does not allocate a displacement map.
No rdev engine or source is included.
