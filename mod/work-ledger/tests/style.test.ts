import { describe, expect, test } from 'claude-code/testing'

import { LEGEND, apportion, barSvg, cells, percent, riskFacts, riskIndicators, stackSegments, statusKey, wholePercents } from '../hooks/style'
import { parseLedger } from '../hooks/view-model'
import { ledgerText, project, thread } from './fixtures'

describe('statusKey', () => {
  test('maps each state to one semantic theme key', () => {
    expect(statusKey('at-risk', 1)).toBe('error')
    expect(statusKey('stale', 40)).toBe('ide')
    expect(statusKey('open', 1)).toBe('inactive')
    expect(statusKey('active', 2)).toBe('inactive')
    // An open thread idle for two weeks is going cold.
    expect(statusKey('open', 14)).toBe('ide')
    expect(statusKey('likely-done', 9)).toBe('success')
    expect(statusKey('done', 9)).toBe('success')
    expect(statusKey('waiting-merge', 3)).toBe('merged')
    expect(statusKey('paused', 3)).toBe('subtle')
    expect(statusKey('something-new', null)).toBe('inactive')
  })
})

describe('riskIndicators', () => {
  test('unpushed tints the name, M/U are badges, the rest goes behind one "!"', () => {
    expect(riskIndicators('unpushed', 4)).toEqual({
      isUnpushed: true,
      badges: [],
      warnings: ['4 not on remote'],
    })
    expect(riskIndicators('modified', 0)).toEqual({
      isUnpushed: false,
      badges: [{ letter: 'M', title: 'modified' }],
      warnings: [],
    })
    expect(riskIndicators('untracked', null, ['3 older at risk']).badges.map(b => b.letter)).toEqual(['U'])
    expect(riskIndicators('modified', 11, ['10 older at risk']).warnings).toEqual([
      '11 not on remote',
      '10 older at risk',
    ])
    expect(riskIndicators('safe', 0)).toEqual({ isUnpushed: false, badges: [], warnings: [] })
    expect(riskIndicators(null, null)).toEqual({ isUnpushed: false, badges: [], warnings: [] })
  })

  test('the detail view keeps the facts in words', () => {
    expect(riskFacts('unpushed', 4)).toEqual(['unpushed', '4 not on remote'])
    expect(riskFacts('modified', 0)).toEqual(['modified'])
    expect(riskFacts('safe', 0)).toEqual([])
  })
})

describe('stackSegments', () => {
  test('one segment per state present, in state order, widths to scale', () => {
    const segments = stackSegments({ stale: 2, 'at-risk': 1, open: 1, done: 0 })
    expect(segments.map(s => [s.state, s.color, s.percent])).toEqual([
      ['at-risk', 'error', 25],
      ['open', 'inactive', 25],
      ['stale', 'ide', 50],
    ])
    expect(stackSegments({})).toEqual([])
  })

  test('bar fills are the light keys, and open and done read apart', () => {
    const fills = Object.fromEntries(
      stackSegments({ 'at-risk': 1, open: 1, stale: 1, done: 1 }).map(s => [s.state, s.fill]),
    )
    expect(fills).toEqual({
      'at-risk': 'diffRemovedDimmed',
      open: 'subtle',
      stale: 'ide',
      done: 'diffAddedDimmed',
    })
    expect(LEGEND.map(l => [l.label, l.fill])).toEqual([
      ['at risk', 'diffRemovedDimmed'],
      ['going cold', 'ide'],
      ['open', 'subtle'],
      ['done', 'diffAddedDimmed'],
    ])
  })

  test('percentages are whole and add up to 100, since the engine takes only "N%"', () => {
    expect(stackSegments({ open: 1, stale: 1, done: 1 }).map(s => s.percent)).toEqual([34, 33, 33])
    expect(stackSegments({ open: 7 }).map(s => s.percent)).toEqual([100])
    expect(wholePercents([1, 2, 3, 4, 5, 6], 21).reduce((a, b) => a + b, 0)).toBe(100)
    expect(wholePercents([0, 0], 0)).toEqual([0, 0])
    expect(percent(33.333)).toBe('33%')
    expect(percent(Number.NaN)).toBe('0%')
    expect(percent(250)).toBe('100%')
    expect(cells(12.6)).toBe(13)
    expect(cells(Number.POSITIVE_INFINITY, 1)).toBe(1)
    expect(cells(-3)).toBe(0)
  })
})

describe('summary counts', () => {
  test('going cold and commits with no backup', () => {
    const parsed = parseLedger(
      ledgerText(
        [project('p1', { git: { risk: 'unpushed', notOnRemote: 3 } }), project('p2', { git: null })],
        [
          thread('a', { effectiveState: 'open', daysIdle: 20 }),
          thread('b', { effectiveState: 'active', daysIdle: 2 }),
          thread('c', { effectiveState: 'stale', daysIdle: 40 }),
          thread('d', { effectiveState: 'at-risk', git: { risk: 'unpushed', notOnRemote: 5 } }),
          thread('e', { git: null }),
        ],
      ),
    )
    if (!parsed.ok) throw new Error(parsed.error.message)
    expect(parsed.view.counts.goingCold).toBe(1)
    expect(parsed.view.counts.unbacked).toBe(8)
  })
})

describe('barSvg', () => {
  test('whole-pixel segments fill the bar exactly, with rounded ends', () => {
    expect(apportion([1, 1, 1], 3, 64)).toEqual([22, 21, 21])
    expect(apportion([0, 0], 0, 64)).toEqual([0, 0])
    const svg = barSvg(
      [
        { value: 1, fill: 'fill-a' },
        { value: 1, fill: 'fill-b' },
        { value: 1, fill: 'fill-c' },
      ],
      64,
      6,
    )
    expect(svg).toMatch(/^<svg [^>]*width="64" height="6" viewBox="0 0 64 6">/)
    expect(svg).toContain('<rect x="0" y="0" width="22" height="6" fill="fill-a"/>')
    expect(svg).toContain('<rect x="22" y="0" width="21" height="6" fill="fill-b"/>')
    expect(svg).toContain('<rect x="43" y="0" width="21" height="6" fill="fill-c"/>')
    expect(svg).toContain('rx="3"')
  })
})
