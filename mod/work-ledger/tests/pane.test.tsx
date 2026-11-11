import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { PALETTES } from '../hooks/palette'
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
    // The summary strip: at risk (recent), going cold, commits with no backup, to review.
    expect(await ui.find({ type: 'Text', text: /^1 at risk$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^0 going cold$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^6 no backup$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^0 to review$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^Updated / })).toBeDefined()
    // Project name first, then the thread title.
    expect((await ui.find({ key: 'row:risk:r1' }))?.text).toMatch(/proj-p1 · Recent risky/)
    // The row's press target is a small "›"; the name sits outside it so its size applies.
    expect((await ui.find({ key: 'risk:r1' }))?.text).toBe('›')
    expect(await ui.find({ key: 'risk:old1' })).toBeUndefined()
    expect(await ui.find({ key: 'riskproj:p1' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /1 older at risk/ })).toBeDefined()
    expect(await ui.find({ key: 'open:o1' })).toBeDefined()
    expect((await ui.find({ key: 'row:project:p2' }))?.text).toMatch(/proj-p2/)
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

const keysStarting = async (ui: { findAll: (q: { type: string }) => Promise<{ key: string | undefined }[]> }, prefix: string) =>
  (await ui.findAll({ type: 'Button' })).filter(b => b.key?.startsWith(prefix)).length

test('a collapsed section shows 3 items and "Show N more" on its label row', { options: OPTIONS }, async ($, on) => {
  engine(on, () => MANY)
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(12), surface })
    expect(await keysStarting(ui, 'risk:')).toBe(3)
    expect(await keysStarting(ui, 'open:')).toBe(3)
    expect((await ui.find({ key: 'more:risk' }))?.text).toBe('Show 12 more')
    expect((await ui.find({ key: 'more:open' }))?.text).toBe('Show 12 more')
    // The link is plain, dim text, not a full button.
    const link = await ui.find({ key: 'more:risk' })
    expect(link?.props.plain).toBe(true)
    expect(link?.props.dimColor).toBe(true)
    await ui.unmount()
  }
})

test('"Show N more" shows the whole section; the others keep their first 3', { options: OPTIONS }, async ($, on) => {
  engine(on, () => MANY)
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    // A small viewport no longer starves the other sections: the body scrolls.
    const ui = await $.ui.mount({ ...paneAt(12), surface })
    await ui.press({ key: 'more:risk' })
    expect(await keysStarting(ui, 'risk:')).toBe(15)
    expect(await ui.find({ key: 'more:risk' })).toBeUndefined()
    expect((await ui.find({ key: 'less:risk' }))?.text).toBe('Show less')
    expect(await keysStarting(ui, 'open:')).toBe(3)
    expect(await ui.find({ key: 'more:open' })).toBeDefined()

    // The expanded state is kept in $.state: a new drawing still shows it.
    await ui.unmount()
    const again = await $.ui.mount({ ...paneAt(12), surface })
    expect(await keysStarting(again, 'risk:')).toBe(15)

    await again.press({ key: 'less:risk' })
    expect(await again.find({ key: 'less:risk' })).toBeUndefined()
    expect(await again.find({ key: 'more:risk' })).toBeDefined()
    expect(await keysStarting(again, 'risk:')).toBe(3)
    await again.unmount()
  }
})

type Part = { type?: string; props?: Record<string, unknown>; children?: unknown[] }
/** Depth-first: the first element under `node` that `hit` accepts. */
function findIn(node: unknown, hit: (p: Part) => boolean): Part | undefined {
  if (typeof node !== 'object' || node === null) return undefined
  const part = node as Part
  if (hit(part)) return part
  for (const child of part.children ?? []) {
    const found = findIn(child, hit)
    if (found) return found
  }
  return undefined
}
type Finder = { find: (q: { key: string }) => Promise<{ children: unknown[] } | undefined> }
const rowOf = async (ui: Finder, key: string) => (await ui.find({ key: `row:${key}` }))
/** The status mark sits outside the row's Button, so its color is drawn on desktop too. */
const markColor = async (ui: Finder, key: string) =>
  findIn(await rowOf(ui, key), p => p.type === 'Text' && JSON.stringify(p.children) === '["●"]')?.props?.color

test('each row starts with a status mark colored by its state', { options: OPTIONS }, async ($, on) => {
  engine(on, () => SAMPLE)
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    expect(await markColor(ui, 'risk:r1')).toBe('error')
    expect(await markColor(ui, 'open:o1')).toBe('inactive')
    await ui.press({ key: 'project:p2' })
    expect(await markColor(ui, 'in:p2:st1')).toBe('ide')
    await ui.press({ key: 'project:p2' })
    await ui.unmount()
  }
})

test('risk facts are compact indicators, not prose', { options: OPTIONS }, async ($, on) => {
  engine(on, () =>
    ledgerText(
      [project('p1', { atRisk: true, git: { risk: 'modified', notOnRemote: 2 } })],
      [
        thread('r1', { effectiveState: 'at-risk', title: 'Unpushed one', git: { risk: 'unpushed', notOnRemote: 4 } }),
        thread('r2', { effectiveState: 'at-risk', title: 'Untracked one', git: { risk: 'untracked', notOnRemote: 0 } }),
      ],
    ),
  )
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    // unpushed: the name is drawn on the tinted background, no chip.
    const r1 = await rowOf(ui, 'risk:r1')
    // Desktop: the palette's at-risk tint with a dark name; terminal: the theme key.
    expect(findIn(r1, p => p.type === 'Box' && p.props?.backgroundColor !== undefined)?.props?.backgroundColor).toBe(
      surface === 'desktop' ? PALETTES.universal.unpushedBackground : 'diffRemovedDimmed',
    )
    if (surface === 'desktop') {
      expect(findIn(r1, p => p.type === 'Text' && p.props?.color === PALETTES.universal.unpushedText)).toBeDefined()
    }
    expect(findIn(r1, p => p.type === 'Text' && /unpushed/.test(JSON.stringify(p.children)))).toBeUndefined()
    // modified and untracked: one-letter badges.
    const letter = (node: unknown, l: string) =>
      findIn(node, p => p.type === 'Text' && JSON.stringify(p.children) === JSON.stringify([l]))
    expect(letter(await rowOf(ui, 'riskproj:p1'), 'M')).toBeDefined()
    expect(letter(await rowOf(ui, 'risk:r2'), 'U')).toBeDefined()
    expect(findIn(await rowOf(ui, 'risk:r2'), p => p.type === 'Box' && p.props?.backgroundColor !== undefined)).toBeUndefined()
    // Other warnings: one "!" whose text shows on hover (desktop) or inline (terminal).
    expect(letter(r1, '!')).toBeDefined()
    const warning = findIn(r1, p => p.type === 'Text' && /4 not on remote/.test(JSON.stringify(p.children)))
    expect(warning).toBeDefined()
    if (surface === 'desktop') {
      const reveal = await ui.find({ key: 'warn:risk:r1' })
      const hidden = findIn(reveal, p => p.type === 'Box' && p.props?.display === 'none')
      expect(hidden).toBeDefined()
      expect(JSON.stringify(hidden)).toMatch(/4 not on remote/)
    } else {
      expect(await ui.find({ key: 'warn:risk:r1' })).toBeUndefined()
    }
    await ui.unmount()
  }
})

test('the per-project bar is drawn to scale on desktop and left out on the terminal', { options: OPTIONS }, async ($, on) => {
  engine(on, () => SAMPLE)
  await $.command.run(LEDGER_COMMAND)

  const desktop = await $.ui.mount({ ...paneAt(40), surface: 'desktop' })
  const bar = await desktop.find({ key: 'bar:p2' })
  const segments = ((bar?.children[0] as Part | undefined)?.children ?? []) as Part[]
  expect(segments.map(s => [s.props?.backgroundColor, s.props?.width])).toEqual([
    [PALETTES.universal.fills.open, '50%'],
    [PALETTES.universal.fills.goingCold, '50%'],
  ])
  // Hovering the bar reveals the counts per state.
  const hidden = findIn(bar, p => p.type === 'Box' && p.props?.display === 'none')
  expect(JSON.stringify(hidden)).toMatch(/1 open · 1 stale/)
  // A legend under the label names the fills.
  for (const word of ['at risk', 'going cold', 'open', 'done']) {
    expect(await desktop.find({ type: 'Text', text: new RegExp(`^${word}$`) })).toBeDefined()
  }
  await desktop.unmount()

  const terminal = await $.ui.mount({ ...paneAt(40), surface: 'terminal' })
  expect(await terminal.find({ key: 'bar:p2' })).toBeUndefined()
  expect(await terminal.find({ type: 'Text', text: /^going cold$/ })).toBeUndefined()
  await terminal.unmount()
})

test('a project row leads with its chevron, colored by its worst state, which toggles it', { options: OPTIONS }, async ($, on) => {
  engine(on, () => SAMPLE)
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    const chevron = await ui.find({ key: 'project:p1' })
    expect(chevron?.text).toBe('▸')
    expect((chevron?.children[0] as Part | undefined)?.props?.color).toBe('error')
    // No status dot beside the chevron.
    expect(await markColor(ui, 'project:p1')).toBeUndefined()
    expect(await ui.find({ key: 'in:p1:r1' })).toBeUndefined()
    await ui.press({ key: 'project:p1' })
    expect((await ui.find({ key: 'project:p1' }))?.text).toBe('▾')
    expect(await ui.find({ key: 'in:p1:r1' })).toBeDefined()
    await ui.press({ key: 'project:p1' })
    expect(await ui.find({ key: 'in:p1:r1' })).toBeUndefined()
    await ui.unmount()
  }
})

test('repos without sessions sit behind one row; their risk stays in Projects at risk', { options: OPTIONS }, async ($, on) => {
  engine(on, () =>
    ledgerText(
      [
        project('p1'),
        project('inv1', { atRisk: true, git: { risk: 'modified', notOnRemote: 0 } }),
        project('inv2'),
      ],
      [thread('t1', { projectId: 'p1' })],
    ),
  )
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    expect(await ui.find({ type: 'Text', text: /^BY PROJECT · 1$/ })).toBeDefined()
    expect((await ui.find({ key: 'row:project:no-sessions' }))?.text).toMatch(/2 repos without sessions/)
    expect(await ui.find({ key: 'row:repo:inv1' })).toBeUndefined()
    expect(await ui.find({ key: 'row:riskproj:inv1' })).toBeDefined()
    await ui.press({ key: 'project:no-sessions' })
    expect(await ui.find({ key: 'row:repo:inv1' })).toBeDefined()
    expect(await ui.find({ key: 'row:repo:inv2' })).toBeDefined()
    await ui.press({ key: 'project:no-sessions' })
    await ui.unmount()
  }
})

test('empty sections say what will appear there', { options: OPTIONS }, async ($, on) => {
  engine(on, () => ledgerText([project('p1')], [thread('s1', { effectiveState: 'stale' })]))
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    expect(await ui.find({ type: 'Text', text: /^Nothing at risk in the last 30 days\.$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^No project at risk\.$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^No open threads\.$/ })).toBeDefined()
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

/** The engine's own rule for a Box size: a finite number of cells, or a whole percentage. */
const ENGINE_PERCENT = /^\d{1,3}%$/
const SIZE_PROPS = ['width', 'height', 'minWidth', 'minHeight'] as const
function badSizes(node: unknown, out: string[] = []): string[] {
  if (typeof node !== 'object' || node === null) return out
  const el = node as Part
  if (el.type === 'Box') {
    for (const prop of SIZE_PROPS) {
      const v = el.props?.[prop]
      if (v === undefined) continue
      const ok = typeof v === 'number' ? Number.isFinite(v) && v >= 0 : typeof v === 'string' && ENGINE_PERCENT.test(v)
      if (!ok) out.push(`${prop}=${JSON.stringify(v)}`)
    }
  }
  for (const child of el.children ?? []) badSizes(child, out)
  return out
}

for (const [name, text] of [
  [
    'a project with no threads, one with a single state and one split in thirds',
    ledgerText(
      [project('empty', { atRisk: true }), project('one'), project('thirds')],
      [
        thread('a', { projectId: 'one', effectiveState: 'stale' }),
        thread('b', { projectId: 'thirds', effectiveState: 'open' }),
        thread('c', { projectId: 'thirds', effectiveState: 'stale' }),
        thread('d', { projectId: 'thirds', effectiveState: 'done' }),
      ],
    ),
  ],
  ['an empty ledger', ledgerText([], [])],
  ['the sample ledger', SAMPLE],
] as const) {
  test(`every Box size is one the engine takes: ${name}`, { options: OPTIONS }, async ($, on) => {
    engine(on, () => text)
    await $.command.run(LEDGER_COMMAND)
    for (const surface of SURFACES) {
      for (const [columns, rows] of [[60, 40], [8, 4]] as const) {
        const pane = paneAt(rows)
        const ui = await $.ui.mount({ ...pane, props: { ...pane.props, bodyColumns: columns }, surface })
        // Expand every project, so bars and thread rows are drawn too.
        for (const b of await ui.findAll({ type: 'Button' })) {
          if (b.key?.startsWith('project:')) await ui.press({ key: b.key })
        }
        expect(badSizes(await ui.drawn())).toEqual([])
        await ui.unmount()
      }
    }
  })
}

/** Every Text whose weight is heavier than regular, or that is drawn bold. */
function heavyTexts(node: unknown, out: string[] = []): string[] {
  if (typeof node !== 'object' || node === null) return out
  const el = node as Part
  if (el.type === 'Text') {
    const w = el.props?.weight
    if (el.props?.bold === true || w === 'bold' || w === 'semibold' || w === 'medium') {
      out.push(JSON.stringify(el.children))
    }
  }
  for (const child of el.children ?? []) heavyTexts(child, out)
  return out
}

/** Every color a Text or Box in the tree carries. */
function colorsIn(node: unknown, out = new Set<unknown>()): Set<unknown> {
  if (typeof node !== 'object' || node === null) return out
  const el = node as Part
  for (const prop of ['color', 'backgroundColor', 'borderColor']) {
    if (el.props?.[prop] !== undefined) out.add(el.props[prop])
  }
  for (const child of el.children ?? []) colorsIn(child, out)
  return out
}

test('no bold and no amber anywhere: hierarchy by size and dim only', { options: OPTIONS }, async ($, on) => {
  engine(on, () =>
    ledgerText(
      [project('p1', { atRisk: true, git: { risk: 'modified', notOnRemote: 3 } }), project('p2')],
      [
        thread('r1', { effectiveState: 'at-risk', git: { risk: 'unpushed', notOnRemote: 4 }, lead: 's-1', sessions: ['s-1'] }),
        thread('c1', { effectiveState: 'open', daysIdle: 20, projectId: 'p2' }),
        thread('s1', { effectiveState: 'stale', daysIdle: 40, projectId: 'p2' }),
      ],
    ),
  )
  await $.command.run(LEDGER_COMMAND)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...paneAt(40), surface })
    await ui.press({ key: 'project:p2' })
    const list = await ui.drawn()
    expect(heavyTexts(list)).toEqual([])
    expect(colorsIn(list).has('warning')).toBe(false)
    // Raw colors come only from the palette, and only on desktop.
    expect([...colorsIn(list)].filter(c => typeof c === 'string' && c.startsWith('#') && !PALETTE_VALUES.has(c))).toEqual([])
    if (surface === 'terminal') expect([...colorsIn(list)].some(c => String(c).startsWith('#'))).toBe(false)
    // A thread going cold is marked blue.
    expect(await markColor(ui, 'open:c1')).toBe('ide')
    await ui.press({ key: 'risk:r1' })
    const detail = await ui.drawn()
    expect(heavyTexts(detail)).toEqual([])
    expect(colorsIn(detail).has('warning')).toBe(false)
    expect([...colorsIn(detail)].filter(c => typeof c === 'string' && c.startsWith('#') && !PALETTE_VALUES.has(c))).toEqual([])
    await ui.press({ key: 'back' })
    await ui.press({ key: 'project:p2' })
    await ui.unmount()
  }
})

const PALETTE_VALUES = new Set(
  Object.values(PALETTES).flatMap(p => [...Object.values(p.fills), p.unpushedBackground, p.unpushedText]),
)

test('colorScheme picks the fills: dark draws the bar and legend from the dark palette', { options: { ...OPTIONS, colorScheme: 'dark' } }, async ($, on) => {
  engine(on, () => SAMPLE)
  await $.command.run(LEDGER_COMMAND)

  const ui = await $.ui.mount({ ...paneAt(40), surface: 'desktop' })
  const bar = await ui.find({ key: 'bar:p2' })
  const segments = ((bar?.children[0] as Part | undefined)?.children ?? []) as Part[]
  expect(segments.map(s => s.props?.backgroundColor)).toEqual([PALETTES.dark.fills.open, PALETTES.dark.fills.goingCold])
  const colors = colorsIn(await ui.drawn())
  for (const fill of [PALETTES.dark.fills.atRisk, PALETTES.dark.fills.done]) expect(colors.has(fill)).toBe(true)
  expect(colors.has(PALETTES.universal.fills.open)).toBe(false)
  await ui.unmount()
})
