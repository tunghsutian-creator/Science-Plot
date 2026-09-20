// Adapted from Tavotto, AGPL-3.0-only. Upstream commit 4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186.
// See web/editor/THIRD_PARTY.md for source files, retained excerpts and modifications.
import {clsx, type ClassValue} from 'clsx'
import {twMerge} from 'tailwind-merge'
export function cn(...inputs:ClassValue[]) { return twMerge(clsx(inputs)) }
