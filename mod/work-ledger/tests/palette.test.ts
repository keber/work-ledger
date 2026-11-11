import { describe, expect, test } from 'claude-code/testing'

import { PALETTES, STATE_FILLS, legendOf, paletteFor, stateFill } from '../hooks/palette'

const HEX = /^#[0-9A-F]{6}$/

describe('palettes', () => {
  test('each palette defines every state, the unpushed colors and nothing else', () => {
    for (const [name, palette] of Object.entries(PALETTES)) {
      expect(Object.keys(palette.fills).sort()).toEqual([...STATE_FILLS].sort())
      for (const value of [...Object.values(palette.fills), palette.unpushedBackground, palette.unpushedText]) {
        expect(value).toMatch(HEX)
      }
      // Every state can be told apart within a palette.
      expect(new Set(Object.values(palette.fills)).size).toBe(STATE_FILLS.length)
      // The unpushed name wears the at-risk fill.
      expect(palette.unpushedBackground).toBe(palette.fills.atRisk)
      expect(name).toMatch(/^(universal|light|dark)$/)
    }
  })

  test('the name text on the unpushed background is dark on light palettes, light on dark', () => {
    const lightness = (hex: string) => parseInt(hex.slice(1, 3), 16) + parseInt(hex.slice(3, 5), 16) + parseInt(hex.slice(5, 7), 16)
    for (const name of ['universal', 'light'] as const) {
      expect(lightness(PALETTES[name].unpushedText)).toBeLessThan(lightness(PALETTES[name].unpushedBackground))
    }
    expect(lightness(PALETTES.dark.unpushedText)).toBeGreaterThan(lightness(PALETTES.dark.unpushedBackground))
  })

  test('colorScheme picks the palette; auto and anything unknown are universal', () => {
    expect(paletteFor('auto').name).toBe('universal')
    expect(paletteFor('light').palette).toBe(PALETTES.light)
    expect(paletteFor('dark').palette).toBe(PALETTES.dark)
    expect(paletteFor('sepia').name).toBe('universal')
  })

  test('states map to fills; stale shares going cold; the legend uses the fills', () => {
    expect(stateFill('at-risk')).toBe('atRisk')
    expect(stateFill('stale')).toBe('goingCold')
    expect(stateFill('open')).toBe('open')
    expect(stateFill('active')).toBe('open')
    expect(stateFill('likely-done')).toBe('done')
    expect(stateFill('waiting-merge')).toBe('waitingMerge')
    expect(stateFill('paused')).toBe('paused')
    expect(legendOf(PALETTES.dark).map(l => l.fill)).toEqual([
      PALETTES.dark.fills.atRisk,
      PALETTES.dark.fills.goingCold,
      PALETTES.dark.fills.open,
      PALETTES.dark.fills.done,
    ])
  })
})
