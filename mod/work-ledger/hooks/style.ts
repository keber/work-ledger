// Pure presentation choices: which theme key shows which state, risk chips and
// the per-project stacked bar. Colors are theme keys only, never literals, so
// the surface maps them for its light and dark themes.

import type { ThemeKey } from 'claude-code'

import { isGoingCold } from './view-model'

/** The glyph every row starts with; its color carries the state. */
export const STATUS_MARK = '●'

/**
 * Going cold and stale: a soft blue, not amber. `ide` is the lightest blue key
 * in the light theme (rgb 71,130,200 against `suggestion`/`permission` 87,105,247
 * and `remember` 0,0,255) and is the same blue in the dark theme. `suggestion`
 * stays the accent, kept for action and selection.
 */
export const COLD: ThemeKey = 'ide'

/** Semantic color of a thread state. The accent is kept for action and selection. */
export function statusKey(state: string, daysIdle: number | null): ThemeKey {
  switch (state) {
    case 'at-risk':
      return 'error'
    case 'stale':
      return COLD
    case 'open':
    case 'active':
      return isGoingCold(state, daysIdle) ? COLD : 'inactive'
    case 'likely-done':
    case 'done':
      return 'success'
    case 'waiting-merge':
      return 'merged'
    case 'paused':
    case 'discarded':
      return 'subtle'
    default:
      return 'inactive'
  }
}

/** Accent for the selected row (an expanded project). */
export const ACCENT: ThemeKey = 'suggestion'
/** Background of a hovered row. */
export const ROW_HOVER: ThemeKey = 'subtle'
/** Border of the two cards: the detail view and the pieces section. */
export const CARD_BORDER: ThemeKey = 'subtle'

/** Background of a row's name when its work is committed but not pushed. */
export const UNPUSHED_BG: ThemeKey = 'diffRemovedDimmed'
/** Color of the one-letter git badges (M, U): the at-risk red. The "!" is dim text. */
export const BADGE: ThemeKey = 'error'

export type Badge = { letter: string; title: string }

/** Compact git risk indicators for a row: no prose, so the name keeps the room. */
export type Indicators = {
  /** The name is drawn on UNPUSHED_BG. */
  isUnpushed: boolean
  /** One letter per uncommitted state: M modified, U untracked. */
  badges: Badge[]
  /** Everything else, behind one "!" whose hover shows these texts. */
  warnings: string[]
}

const BADGES: Record<string, Badge> = {
  modified: { letter: 'M', title: 'modified' },
  untracked: { letter: 'U', title: 'untracked' },
}

export function riskIndicators(
  risk: string | null,
  notOnRemote: number | null,
  extraWarnings: readonly string[] = [],
): Indicators {
  const badge = risk === null ? undefined : BADGES[risk]
  return {
    isUnpushed: risk === 'unpushed',
    badges: badge ? [badge] : [],
    warnings: [...(notOnRemote ? [`${notOnRemote} not on remote`] : []), ...extraWarnings],
  }
}

/** The same facts in words, for the detail view. */
export function riskFacts(risk: string | null, notOnRemote: number | null): string[] {
  return [
    ...(risk !== null && (risk === 'unpushed' || BADGES[risk]) ? [risk] : []),
    ...(notOnRemote ? [`${notOnRemote} not on remote`] : []),
  ]
}

const STATE_ORDER = [
  'at-risk',
  'open',
  'waiting-merge',
  'active',
  'paused',
  'stale',
  'likely-done',
  'done',
  'discarded',
]

export type Segment = { state: string; count: number; color: ThemeKey; fill: ThemeKey; percent: number }

/**
 * Light fills for large areas (the per-project bar and its legend). Full-strength
 * error and success read heavy as fills, so the dimmed diff keys stand in. The
 * going cold and stale take COLD (blue, no amber anywhere); open is `subtle`, the
 * lightest neutral key (no lighter grey exists), clearly apart from done's green.
 */
export function fillKey(state: string): ThemeKey {
  switch (state) {
    case 'at-risk':
      return 'diffRemovedDimmed'
    case 'stale':
      return COLD
    case 'likely-done':
    case 'done':
      return 'diffAddedDimmed'
    case 'waiting-merge':
      return 'merged'
    case 'paused':
    case 'discarded':
      return 'inactive'
    default:
      return 'subtle'
  }
}

/** The By project legend: the four fills a reader needs to tell apart. */
export const LEGEND: readonly { label: string; fill: ThemeKey }[] = [
  { label: 'at risk', fill: fillKey('at-risk') },
  { label: 'going cold', fill: fillKey('stale') },
  { label: 'open', fill: fillKey('open') },
  { label: 'done', fill: fillKey('done') },
]

/** Segments of a project's stacked bar: one per state present, widths to scale. */
export function stackSegments(counts: Readonly<Record<string, number>>): Segment[] {
  const states = [
    ...STATE_ORDER.filter(s => (counts[s] ?? 0) > 0),
    ...Object.keys(counts).filter(s => !STATE_ORDER.includes(s) && (counts[s] ?? 0) > 0),
  ]
  const total = states.reduce((sum, s) => sum + counts[s]!, 0)
  const percents = wholePercents(states.map(s => counts[s]!), total)
  return states.map((state, i) => ({
    state,
    count: counts[state]!,
    // The bar shows the state mix, so a stale count is drawn as stale, not cold.
    color: statusKey(state, null),
    fill: fillKey(state),
    percent: percents[i]!,
  }))
}

/**
 * Whole percentages that add up to 100 (largest remainder). The engine takes a
 * Box size only as a number of cells or a whole percentage (`/^\d{1,3}%$/`), so
 * "33.3%" makes it refuse the whole tree.
 */
export function wholePercents(values: readonly number[], total: number): number[] {
  if (!(total > 0)) return values.map(() => 0)
  const exact = values.map(v => (Math.max(0, v) / total) * 100)
  const floors = exact.map(Math.floor)
  let left = 100 - floors.reduce((a, b) => a + b, 0)
  const order = exact.map((x, i) => ({ i, rest: x - floors[i]! })).sort((a, b) => b.rest - a.rest || a.i - b.i)
  for (const { i } of order) {
    if (left <= 0) break
    floors[i]! += 1
    left--
  }
  return floors.map(p => Math.min(100, Math.max(0, p)))
}

/** A Box size the engine accepts: a whole, finite number of cells, or "N%" with N 0..100. */
export const cells = (n: number, min = 0): number => (Number.isFinite(n) ? Math.max(min, Math.round(n)) : min)
export const percent = (p: number): string => `${cells(Math.min(100, p))}%`
