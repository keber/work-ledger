// The mod's own fills for state areas: the per-project bar, its legend swatches
// and the unpushed name background. Theme keys rendered too strong (`ide`) or too
// dark (`subtle`) as fills on the desktop, and a mod cannot tell whether the app
// is light or dark, so these are raw colors, picked by the `colorScheme` option.
// This is the one module that holds hex colors. Text stays on theme keys.

export type PaletteName = 'universal' | 'light' | 'dark'
export type StateFill = 'atRisk' | 'goingCold' | 'open' | 'done' | 'waitingMerge' | 'paused'

export type Palette = {
  fills: Readonly<Record<StateFill, string>>
  /** Background of a row name whose commits are not pushed (the at-risk fill). */
  unpushedBackground: string
  /** Text color of that name, so it stays readable on the background. */
  unpushedText: string
}

/** Mid-light tints that read on a white and on a near-black background. */
const universal: Palette = {
  fills: {
    atRisk: '#F2B8C0',
    goingCold: '#9CCBF0',
    open: '#C9CDD2',
    done: '#A8DDB8',
    waitingMerge: '#C9B8EE',
    paused: '#E3E5E8',
  },
  unpushedBackground: '#F2B8C0',
  unpushedText: '#1F2328',
}

/** Lighter pastels for a white background. */
const light: Palette = {
  fills: {
    atRisk: '#F9D3D9',
    goingCold: '#C4E1F7',
    open: '#DEE1E5',
    done: '#CDEBD6',
    waitingMerge: '#E0D6F6',
    paused: '#EFF1F3',
  },
  unpushedBackground: '#F9D3D9',
  unpushedText: '#1F2328',
}

/** Deeper, desaturated versions of the same hues for a near-black background. */
const dark: Palette = {
  fills: {
    atRisk: '#7D4049',
    goingCold: '#3D6A8E',
    open: '#545A61',
    done: '#3F6E4F',
    waitingMerge: '#5E4D85',
    paused: '#3A3E43',
  },
  unpushedBackground: '#7D4049',
  unpushedText: '#F0F2F4',
}

export const PALETTES: Readonly<Record<PaletteName, Palette>> = { universal, light, dark }

export const STATE_FILLS: readonly StateFill[] = ['atRisk', 'goingCold', 'open', 'done', 'waitingMerge', 'paused']

/** `colorScheme`: `light` or `dark` match the app theme; `auto` (or anything else) is `universal`. */
export function paletteFor(colorScheme: string): { name: PaletteName; palette: Palette } {
  const name: PaletteName = colorScheme === 'light' || colorScheme === 'dark' ? colorScheme : 'universal'
  return { name, palette: PALETTES[name] }
}

/** Which fill a ledger state takes; stale shares going cold's. */
export function stateFill(state: string): StateFill {
  switch (state) {
    case 'at-risk':
      return 'atRisk'
    case 'stale':
      return 'goingCold'
    case 'likely-done':
    case 'done':
      return 'done'
    case 'waiting-merge':
      return 'waitingMerge'
    case 'paused':
    case 'discarded':
      return 'paused'
    default:
      return 'open'
  }
}

/** The legend under By project: the swatches are the bar's own fills. */
export function legendOf(palette: Palette): { label: string; fill: string }[] {
  return [
    { label: 'at risk', fill: palette.fills.atRisk },
    { label: 'going cold', fill: palette.fills.goingCold },
    { label: 'open', fill: palette.fills.open },
    { label: 'done', fill: palette.fills.done },
  ]
}
