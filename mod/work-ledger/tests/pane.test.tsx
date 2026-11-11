import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { day, ledgerText, project, thread } from './fixtures'

const LEDGER_PATH = 'C:/fixture/out/ledger.json'
const OPTIONS = {
  ledgerPath: LEDGER_PATH,
  projectRoot: 'C:/fixture',
  pythonCommand: 'py-fixture',
}

const paneAt = (bodyRows: number) =>
  ({
    plugin: 'work-ledger',
    component: 'Pane',
    requestId: 'work-ledger',
    props: {
      title: 'Work ledger',
      isFocused: false,
      bodyColumns: 60,
      placement: 'dock',
      scroll: { offset: 0, bodyRows },
      view: {},
    },
  }) as const

const LEDGER_COMMAND = {
  command: 'ledger',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 160 },
} as const

const SURFACES = ['terminal', 'desktop'] as const

const SAMPLE = ledgerText(
  [project('p1', { atRisk: true, git: { risk: 'modified', notOnRemote: 2 } }), project('p2')],
  [
    thread('r1', {
      effectiveState: 'at-risk',
      title: 'Recent risky',
      git: { risk: 'unpushed', notOnRemote: 4 },
      sessions: ['s-2', 's-1'],
      lead: 's-1',
      resume: { lastRecap: 'Synthetic recap', lastAsk: null, lastPrompt: 'Synthetic prompt' },
      related: [{ id: 'o1', sharedMessages: 3, reason: 'fork-family' }],
    }),
    thread('old1', { effectiveState: 'at-risk', recency: 'old', daysIdle: 200 }),
    thread('o1', { effectiveState: 'open', title: 'Open one', projectId: 'p2' }),
    thread('st1', { effectiveState: 'stale', title: 'Stale one', projectId: 'p2' }),
  ],
)

function engine(on: On, files: () => string | Error) {
  const reads: string[] = []
  on('command.register', () => ({ value: { command: 'ledger' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('fs.read', (_, e) => {
    reads.push(e.path)
    const file = files()
    return file instanceof Error ? { deny: file.message } : { value: file }
  })
  return reads
}

test('the list shows each section and the header counts', { options: OPTIONS }, async ($, on) => {
  const reads = engine(on, () => SAMPLE)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.command.run(LEDGER_COMMAND)
  // The engine may hand the path on with the platform's separators.
  expect(reads.map(p => p.replaceAll('\\', '/'))).toEqual([LEDGER_PATH])

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    expect(await ui.find({ text: /1 projects at risk · 2 threads at risk · 1 open/ })).toBeDefined()
    expect((await ui.find({ key: 'risk:r1' }))?.text).toMatch(/proj-p1 · Recent risky · 1d · unpushed, 4 not on remote/)
    expect(await ui.find({ key: 'risk:old1' })).toBeUndefined()
    expect(await ui.find({ text: /proj-p1 · modified, 2 not on remote · 1d · 1 older at risk/ })).toBeDefined()
    expect(await ui.find({ key: 'open:o1' })).toBeDefined()
    expect((await ui.find({ key: 'project:p2' }))?.text).toMatch(/proj-p2 · 1 open, 1 stale/)
    // Stale threads appear only once their project is expanded.
    expect(await ui.find({ text: /Stale one/ })).toBeUndefined()
    await ui.press({ key: 'project:p2' })
    expect(await ui.find({ key: 'in:p2:st1' })).toBeDefined()
    await ui.press({ key: 'project:p2' })
    await ui.unmount()
  }
})

test('selecting a thread shows its detail, and Back returns', { options: OPTIONS }, async ($, on) => {
  engine(on, () => SAMPLE)
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    await ui.press({ key: 'risk:r1' })
    expect(await ui.find({ text: /claude --resume s-1/ })).toBeDefined()
    expect(await ui.find({ text: /s-1 \(lead\)/ })).toBeDefined()
    expect(await ui.find({ text: /Synthetic recap/ })).toBeDefined()
    expect(await ui.find({ key: 'related:o1' })).toBeDefined()
    await ui.press({ key: 'related:o1' })
    expect(await ui.find({ text: /Open one/ })).toBeDefined()
    await ui.press({ key: 'back' })
    expect(await ui.find({ key: 'refresh' })).toBeDefined()
    await ui.unmount()
  }
})

const MANY = ledgerText(
  [project('p1', { atRisk: true })],
  Array.from({ length: 30 }, (_, i) =>
    thread(`t${i}`, { effectiveState: i < 15 ? 'at-risk' : 'open', lastAt: day((i % 28) + 1) }),
  ),
)

/**
 * Rows the tree takes on the terminal: a row Box, a Text or a Button is one
 * row; a `marginTop: 'md'` adds one; `rowGap: 'xs'` adds none there.
 */
function countRows(node: unknown): number {
  if (typeof node !== 'object' || node === null) return 0
  const el = node as { type: string; props?: Record<string, unknown>; children?: unknown[] }
  const margin = el.props?.marginTop === 'md' ? 1 : 0
  if (el.type === 'Box' && el.props?.flexDirection !== 'row') {
    return margin + (el.children ?? []).reduce<number>((sum, c) => sum + countRows(c), 0)
  }
  return margin + 1
}

const keysStarting = async (ui: { findAll: (q: { type: string }) => Promise<{ key: string | undefined }[]> }, prefix: string) =>
  (await ui.findAll({ type: 'Button' })).filter(b => b.key?.startsWith(prefix)).length

test('the lists fit the rows given, ending in a "+N more" control', { options: OPTIONS }, async ($, on) => {
  engine(on, () => MANY)
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const rows = 20
    const ui = await $.ui.mount({ ...paneAt(rows), surface })
    expect(countRows(await ui.drawn())).toBeLessThanOrEqual(rows)
    expect((await ui.find({ key: 'more:risk' }))?.text).toMatch(/^\+\d+ more$/)
    expect((await ui.find({ key: 'more:open' }))?.text).toMatch(/^\+\d+ more$/)
    await ui.unmount()
  }
})

test('"+N more" shows the whole section and "Show less" folds it again', { options: OPTIONS }, async ($, on) => {
  engine(on, () => MANY)
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(20), surface })
    expect(await keysStarting(ui, 'risk:')).toBeLessThan(15)

    await ui.press({ key: 'more:risk' })
    expect(await keysStarting(ui, 'risk:')).toBe(15)
    expect(await ui.find({ key: 'more:risk' })).toBeUndefined()
    expect((await ui.find({ key: 'less:risk' }))?.text).toBe('Show less')
    // The other sections give way but stay reachable through their own control.
    expect(await ui.find({ key: 'more:open' })).toBeDefined()

    // The expanded state is kept in $.state: a new drawing still shows it.
    await ui.unmount()
    const again = await $.ui.mount({ ...paneAt(20), surface })
    expect(await keysStarting(again, 'risk:')).toBe(15)

    await again.press({ key: 'less:risk' })
    expect(await again.find({ key: 'less:risk' })).toBeUndefined()
    expect(await again.find({ key: 'more:risk' })).toBeDefined()
    expect(countRows(await again.drawn())).toBeLessThanOrEqual(20)
    await again.unmount()
  }
})

test('item data is drawn dim and in the smaller size; titles are not', { options: OPTIONS }, async ($, on) => {
  engine(on, () => SAMPLE)
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    const row = await ui.find({ key: 'risk:r1' })
    const parts = (row?.children ?? []) as { type?: string; props?: Record<string, unknown>; children?: unknown[] }[]
    const data = parts.find(p => p.props?.dimColor === true)
    expect(data?.props?.size).toBe('footnote')
    expect(JSON.stringify(data?.children)).toMatch(/unpushed, 4 not on remote/)
    const name = parts.find(p => p.props?.dimColor !== true)
    expect(name?.props?.size).toBe('footnote')
    const heading = await ui.find({ type: 'Text', text: /^At risk, recent/ })
    expect(heading?.props.size).toBeUndefined()
    await ui.unmount()
  }
})

for (const [name, file, pattern] of [
  ['a missing ledger', new Error('ENOENT: no such file'), /Cannot read C:\/fixture\/out\/ledger.json/],
  ['malformed JSON', '{"schemaVersion": 2,', /Malformed JSON/],
  ['an unknown schemaVersion', ledgerText([], [], { schemaVersion: 1 }), /unsupported version/],
] as const) {
  test(`${name} is said in the pane, which offers Refresh`, { options: OPTIONS }, async ($, on) => {
    engine(on, () => file)
    await $.command.run(LEDGER_COMMAND)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ ...paneAt(30), surface })
      expect(await ui.find({ type: 'Text', text: pattern })).toBeDefined()
      expect(await ui.find({ key: 'refresh' })).toBeDefined()
      await ui.unmount()
    }
  })
}

test('Refresh runs the CLI, re-reads the ledger and says so', { options: OPTIONS }, async ($, on) => {
  const reads = engine(on, () => SAMPLE)
  const clock = mock.clock(on)
  const runs: unknown[] = []
  const toasts: string[] = []
  on('process.run', (_, e) => {
    runs.push({ argv: e.argv, init: e.init })
    return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.toast', (_, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  await $.command.run(LEDGER_COMMAND)

  const ui = await $.ui.mount({ ...paneAt(40), surface: 'desktop' })
  await ui.press({ key: 'refresh' })
  await clock.settle()
  expect(runs).toEqual([
    {
      argv: ['py-fixture', '-m', 'work_ledger', 'refresh'],
      init: { cwd: 'C:/fixture', env: { PYTHONPATH: 'src' }, timeoutMs: 600000 },
    },
  ])
  expect(reads).toHaveLength(2)
  expect(toasts).toEqual(['Ledger refreshed.'])
  expect((await ui.find({ key: 'refresh' }))?.text).toBe('Refresh')
  await ui.unmount()
})

test('a failed Refresh toasts the exit code and the last stderr line', { options: OPTIONS }, async ($, on) => {
  const reads = engine(on, () => SAMPLE)
  const clock = mock.clock(on)
  const toasts: string[] = []
  let exitCode = 2
  on('process.run', () =>
    exitCode === 2
      ? {
          value: {
            exitCode,
            stdout: '',
            stderr: 'Traceback\nValueError: synthetic failure\n',
            isStdoutTruncated: false,
            isStderrTruncated: false,
          },
        }
      : { deny: 'spawn py-fixture ENOENT' },
  )
  on('ui.toast', (_, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  await $.command.run(LEDGER_COMMAND)

  const ui = await $.ui.mount({ ...paneAt(40), surface: 'desktop' })
  await ui.press({ key: 'refresh' })
  await clock.settle()
  exitCode = -1
  await ui.press({ key: 'refresh' })
  await clock.settle()
  expect(toasts).toEqual([
    'Refresh failed (exit 2): ValueError: synthetic failure',
    expect.stringMatching(/^Refresh failed: .*ENOENT/),
  ])
  expect(reads).toHaveLength(1)
  expect((await ui.find({ key: 'refresh' }))?.text).toBe('Refresh')
  await ui.unmount()
})

test('the Refresh press returns at once and the run finishes in the background', { options: OPTIONS }, async ($, on) => {
  const reads = engine(on, () => SAMPLE)
  const clock = mock.clock(on)
  const toasts: string[] = []
  let runs = 0
  on('process.run', async () => {
    runs++
    // A refresh takes minutes: far past any press budget.
    await clock.sleep(150_000)
    return {
      value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
    }
  })
  on('ui.toast', (_, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  await $.command.run(LEDGER_COMMAND)

  const ui = await $.ui.mount({ ...paneAt(40), surface: 'desktop' })
  // The press resolves with the clock standing still: it did not wait for the run.
  await ui.press({ key: 'refresh' })
  expect((await ui.find({ key: 'refresh' }))?.text).toBe('Refreshing…')

  await clock.settle()
  expect(runs).toBe(1)
  expect(toasts).toEqual([])
  // A second press while it runs starts nothing.
  await ui.press({ key: 'refresh' })
  await clock.settle()
  expect(runs).toBe(1)
  expect((await ui.find({ key: 'refresh' }))?.text).toBe('Refreshing…')

  await clock.advance(150_000)
  expect(toasts).toEqual(['Ledger refreshed.'])
  expect(reads).toHaveLength(2)
  expect((await ui.find({ key: 'refresh' }))?.text).toBe('Refresh')
  await ui.unmount()
})

const HOME_OPTIONS = {
  ledgerPath: '~/wl/out/ledger.json',
  projectRoot: '~/wl',
  pythonCommand: 'py-fixture',
}

test('paths starting with ~ resolve under USERPROFILE', { options: HOME_OPTIONS }, async ($, on) => {
  const reads = engine(on, () => SAMPLE)
  mock.env(on, { USERPROFILE: 'D:\\home\\jdoe', HOME: '/ignored' })
  const clock = mock.clock(on)
  const cwds: unknown[] = []
  on('process.run', (_, e) => {
    cwds.push(e.init?.cwd)
    return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.toast', () => ({ value: undefined }))
  await $.command.run(LEDGER_COMMAND)
  expect(reads.map(p => p.replaceAll('\\', '/'))).toEqual(['D:/home/jdoe/wl/out/ledger.json'])

  const ui = await $.ui.mount({ ...paneAt(40), surface: 'desktop' })
  await ui.press({ key: 'refresh' })
  await clock.settle()
  expect(cwds).toEqual(['D:/home/jdoe/wl'])
  await ui.unmount()
})

test('without USERPROFILE, ~ resolves under HOME', { options: HOME_OPTIONS }, async ($, on) => {
  const reads = engine(on, () => SAMPLE)
  mock.env(on, { HOME: '/home/jdoe' })
  await $.command.run(LEDGER_COMMAND)
  // On Windows the engine resolves a rooted POSIX path onto the current drive.
  expect(reads).toHaveLength(1)
  expect(reads[0]?.replaceAll('\\', '/')).toMatch(/^([A-Za-z]:)?\/home\/jdoe\/wl\/out\/ledger\.json$/)
})
