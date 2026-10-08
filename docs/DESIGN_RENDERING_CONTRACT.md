# Rendering contract and visual compatibility

Rendering equivalence is a separate gate from scientific correctness, native
state audit, clipping and self-rebuild equality. The reference is the retained
production renderer and its source-controlled policy, not Figure Grammar defaults.

## Authority and migration

New FigureTemplate creation pins `RenderingStyleContract` identity and content
hash in the presentation projection. The immutable packaged snapshot records
each value's old source and distinguishes prescribed values from unspecified
properties and observed adapter behavior. Theme and explicit figure/view/layer/
mark overrides remain presentation variations with traceable precedence.
Existing unbound FigureSpec v2 revisions retain their original interpretation;
reading or rebuilding them never silently inserts a different visual contract.
Legacy VSZ remains authoritative and no user artifact is rewritten by this work.

## Compiler boundary

The semantic compiler resolves the contract, palette assignment, scoped styles,
physical panel constraints and guide typography before backend lowering. The
backend receives resolved axis padding, ticks, legend entries and styles. Native
text metrics are a renderer responsibility and are checked after rendering;
they do not authorize automatic font, margin or canvas changes. No Veusz path
or arbitrary native setting enters the canonical document.

The fixed single-panel house frame comes from the old policy. Explicit layout
overrides are recorded; the solver must reject insufficient space rather than
enlarge or shrink prescribed geometry. Multi-panel placement is identified by a
separate `sciplot-figure-composition-v1` policy. It inherits in-panel styling but
does not claim an old multi-panel layout precedent.

## Verification

Regression fixtures use identical source arrays in the retained old pipeline
and new Managed compiler. Evidence contains structural per-property differences,
native renders, difference images, changed bounds and quantitative metrics.
Negative controls must detect altered fonts, strokes and geometry. Unspecified
old behavior is reported separately, never invented as a historical rule.
Historical user-edited figures supply evidence of explicit overrides, not a new
universal default. Native environment and source hashes accompany comparisons.

The final acceptance report must state the tested compatibility scope and any
remaining inequivalent properties. Self-rebuild identity cannot substitute for
this independent Rendering Contract Regression.
