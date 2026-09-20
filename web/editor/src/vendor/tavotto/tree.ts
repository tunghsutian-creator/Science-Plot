// Adapted from Tavotto, AGPL-3.0-only. Upstream commit 4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186.
// See web/editor/THIRD_PARTY.md for source files, retained excerpts and modifications.
// TreeRow.tsx lines 15-18; same native tree indentation as upstream.
export const TREE_INDENT = 14
export const treeIndent = (depth:number, base=8) => ({paddingLeft:base+depth*TREE_INDENT})
