import { describe, expect, test } from 'claude-code/testing'

import type { LedgerView } from '../types'
import {
  clip,
  expandHome,
  fitList,
  formatAge,
  formatCounts,
  lastLine,
  parseLedger,
  splitClip,
  projectRows,
  readError,
  toMs,
} from '../hooks/view-model'
import { day, ledgerText, project, thread } from './fixtures'

function viewOf(text: string): LedgerView {
  const parsed = parseLedger(text)
  if (!parsed.ok) throw new Error(`expected a view, got ${parsed.error.message}`)
  return parsed.view
}

describe('parseLedger', () => {
  test('at-risk threads split into recent (listed) and old (counted per project)', () => {
    const view = viewOf(
      ledgerText(
        [project('p1', { atRisk: true })],
        [
          thread('a', { effectiveState: 'at-risk', recency: 'recent', lastAt: day(3) }),
          thread('b', { effectiveState: 'at-risk', recency: 'recent', lastAt: day(8) }),
          thread('c', { effectiveState: 'at-risk', recency: 'old', lastAt: day(1), daysIdle: 120 }),
          thread('d', { effectiveState: 'open' }),
        ],
      ),
    )
    expect(view.atRiskRecent).toEqual(['b', 'a'])
    expect(view.counts.threadsAtRisk).toBe(3)
    expect(view.projectsById.p1?.oldAtRiskCount).toBe(1)
  })

  test('projects at risk keep ledger order and carry the main worktree risk', () => {
    const view = viewOf(
      ledgerText(
        [
          project('p1', { atRisk: true, git: { risk: 'modified', notOnRemote: 3 } }),
          project('p2'),
          project('p3', { atRisk: true, git: null, daysIdle: null }),
        ],
        [],
      ),
    )
    expect(view.projectsAtRisk).toEqual(['p1', 'p3'])
    expect(view.counts.projectsAtRisk).toBe(2)
    expect(view.projectsById.p1).toMatchObject({ risk: 'modified', notOnRemote: 3 })
    expect(view.projectsById.p3).toMatchObject({ risk: null, notOnRemote: null, daysIdle: null })
  })

  test('open lists open and active threads, newest first, at most 15', () => {
    const threads = Array.from({ length: 20 }, (_, i) =>
      thread(`t${i + 1}`, { effectiveState: i % 2 ? 'active' : 'open', lastAt: day(i + 1) }),
    )
    threads.push(thread('s', { effectiveState: 'stale', lastAt: day(28) }))
    const view = viewOf(ledgerText([project('p1')], threads))
    expect(view.open).toHaveLength(15)
    expect(view.open[0]).toBe('t20')
    expect(view.open[14]).toBe('t6')
    expect(view.counts.open).toBe(20)
  })

  test('counts threads per project and effective state', () => {
    const view = viewOf(
      ledgerText(
        [project('p1'), project('p2')],
        [
          thread('a', { effectiveState: 'at-risk' }),
          thread('b', { effectiveState: 'open' }),
          thread('c', { effectiveState: 'stale', projectId: 'p2' }),
          thread('d', { effectiveState: 'open' }),
          thread('e', { effectiveState: 'likely-done', projectId: 'p2' }),
        ],
      ),
    )
    expect(view.projectsById.p1?.counts).toEqual({ 'at-risk': 1, open: 2 })
    expect(view.projectsById.p1?.threadIds).toEqual(['a', 'b', 'd'])
    expect(view.projectsById.p2?.counts).toEqual({ stale: 1, 'likely-done': 1 })
    expect(formatCounts(view.projectsById.p2!.counts)).toBe('1 stale, 1 likely-done')
  })

  test('a thread whose project is unknown goes under "(no project)"', () => {
    const view = viewOf(ledgerText([project('p1')], [thread('a', { projectId: 'gone' })]))
    expect(view.threads.a?.projectName).toBe('(no project)')
    expect(view.projects).toHaveLength(2)
  })

  test('thread detail: lead first, resume texts, override state, known related only', () => {
    const view = viewOf(
      ledgerText(
        [project('p1')],
        [
          thread('a', {
            sessions: ['s-old', 's-lead', 's-mid'],
            lead: 's-lead',
            resume: { lastRecap: 'recap text', lastAsk: 'ask text', lastPrompt: 'prompt text' },
            state: 'paused',
            effectiveState: 'paused',
            note: 'a note',
            related: [
              { id: 'b', sharedMessages: 4, reason: 'fork-family' },
              { id: 'missing', sharedMessages: 1, reason: 'fork-family' },
            ],
          }),
          thread('b'),
        ],
      ),
    )
    expect(view.threads.a).toMatchObject({
      title: 'Thread a',
      projectName: 'proj-p1',
      sessions: ['s-lead', 's-old', 's-mid'],
      lead: 's-lead',
      recap: 'recap text',
      ask: 'ask text',
      lastPrompt: 'prompt text',
      state: 'paused',
      effectiveState: 'paused',
      note: 'a note',
      related: ['b'],
    })
  })

  test('malformed JSON is an error carrying the parse message', () => {
    const parsed = parseLedger('{"schemaVersion": 2, ')
    expect(parsed.ok).toBe(false)
    if (parsed.ok) return
    expect(parsed.error.kind).toBe('malformed')
    expect(parsed.error.message).toMatch(/^Malformed JSON: .+/)
  })

  test('an unknown schemaVersion is unsupported', () => {
    for (const version of [1, 3, '2', undefined]) {
      const parsed = parseLedger(ledgerText([], [], { schemaVersion: version }))
      expect(parsed.ok).toBe(false)
      if (parsed.ok) continue
      expect(parsed.error.kind).toBe('unsupported')
      expect(parsed.error.message).toMatch(/unsupported version/)
    }
  })

  test('a ledger without lists, or not an object, is invalid', () => {
    const noLists = parseLedger(JSON.stringify({ schemaVersion: 2 }))
    expect(noLists.ok ? '' : noLists.error.kind).toBe('invalid')
    const array = parseLedger('[]')
    expect(array.ok ? '' : array.error.kind).toBe('invalid')
  })

  test('a file that cannot be read is reported as missing, naming the path', () => {
    const error = readError('C:/fixture/ledger.json', new Error('ENOENT: no such file'))
    expect(error.kind).toBe('missing')
    expect(error.message).toBe('Cannot read C:/fixture/ledger.json: ENOENT: no such file')
  })
})

describe('helpers', () => {
  test('timestamps with microseconds parse', () => {
    expect(toMs('2026-01-10T12:00:00.123456+00:00')).toBe(Date.UTC(2026, 0, 10, 12, 0, 0, 123))
    expect(toMs('not a date')).toBe(null)
  })

  test('formatAge', () => {
    const at = '2026-01-10T12:00:00.000000+00:00'
    const base = Date.UTC(2026, 0, 10, 12)
    expect(formatAge(at, base + 20_000)).toBe('just now')
    expect(formatAge(at, base + 5 * 60_000)).toBe('5 min ago')
    expect(formatAge(at, base + 3 * 3_600_000)).toBe('3 h ago')
    expect(formatAge(at, base + 72 * 3_600_000)).toBe('3 d ago')
    expect(formatAge('garbage', base)).toBe('at an unknown time')
  })

  test('splitClip fits a name and its data on one line, cutting the name first', () => {
    expect(splitClip('name', ' · 3d', 20)).toEqual(['name', ' · 3d'])
    expect(splitClip('a long project name', ' · 3d', 12)).toEqual(['a long…', ' · 3d'])
    expect(splitClip('name', ' · much too long data', 10)).toEqual(['n…', ' · much…'])
  })

  test('fitList leaves a row for "+N more" when it truncates', () => {
    expect(fitList([1, 2, 3], 3)).toEqual({ shown: [1, 2, 3], more: 0 })
    expect(fitList([1, 2, 3, 4, 5], 3)).toEqual({ shown: [1, 2], more: 3 })
    expect(fitList([1, 2], 0)).toEqual({ shown: [], more: 0 })
  })

  test('clip cuts to one line', () => {
    expect(clip('a\nb  c', 10)).toBe('a b c')
    expect(clip('abcdefghij', 5)).toBe('abcd…')
  })

  test('lastLine finds the last non-empty stderr line', () => {
    expect(lastLine('one\r\ntwo\n\n')).toBe('two')
    expect(lastLine('')).toBe('')
  })

  test('projectRows expands only the expanded projects', () => {
    const view = viewOf(
      ledgerText([project('p1'), project('p2')], [thread('a'), thread('b', { projectId: 'p2' })]),
    )
    expect(projectRows(view, ['p2']).map(r => (r.kind === 'project' ? r.projectId : r.threadId))).toEqual([
      'p1',
      'p2',
      'b',
    ])
  })

  test('expandHome replaces a leading ~ with the home dir, forward slashes', () => {
    const home = 'D:\\home\\jdoe\\'
    expect(expandHome('~/wl/out/ledger.json', home)).toBe('D:/home/jdoe/wl/out/ledger.json')
    expect(expandHome('~\\wl', home)).toBe('D:/home/jdoe/wl')
    expect(expandHome('~', home)).toBe('D:/home/jdoe')
    expect(expandHome('~/x', '/home/jdoe')).toBe('/home/jdoe/x')
  })

  test('expandHome leaves other paths, and ~ without a home dir, unchanged', () => {
    expect(expandHome('D:/wl/ledger.json', 'D:/home/jdoe')).toBe('D:/wl/ledger.json')
    expect(expandHome('~other/x', 'D:/home/jdoe')).toBe('~other/x')
    expect(expandHome('a/~/b', 'D:/home/jdoe')).toBe('a/~/b')
    expect(expandHome('~/x', undefined)).toBe('~/x')
    expect(expandHome('~/x', '  ')).toBe('~/x')
  })
})
