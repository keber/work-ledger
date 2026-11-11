import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { ledgerText, project, thread } from './fixtures'
import { frontMatterOf, indexText, pieceEntry, pieceFile } from './pieces-fixtures'

const ROOT = 'C:/fixture'
const PIECES = `${ROOT}/out/pieces/inbox`
const OPTIONS = {
  ledgerPath: `${ROOT}/out/ledger.json`,
  projectRoot: ROOT,
  pythonCommand: 'py-fixture',
  piecesDir: PIECES,
}
const LEDGER_COMMAND = {
  command: 'ledger',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 160 },
} as const
const PANE = {
  plugin: 'work-ledger',
  component: 'Pane',
  requestId: 'work-ledger',
  props: {
    title: 'Work ledger',
    isFocused: false,
    bodyColumns: 70,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const
const SURFACES = ['terminal', 'desktop'] as const

const LEDGER = ledgerText(
  [project('p1', { atRisk: true })],
  [thread('r1', { effectiveState: 'at-risk', title: 'Ledger title r1' }), thread('o1')],
)

const TEAM = pieceEntry('2026-01-10-team-1', {
  relevance: 0.8,
  sourceThreadIds: ['r1', 'gone'],
  sourceThreads: [
    { id: 'r1', title: 'Index title r1', project: 'proj-p1' },
    { id: 'gone', title: 'Index title gone', project: 'proj-p1' },
  ],
})
const PUBLIC = pieceEntry('2026-01-10-public-1', { relevance: 0.6 })
const DONE = pieceEntry('2026-01-10-team-2', { status: 'approved', title: 'Already approved' })

type Files = Record<string, string | Error>

/** The engine beneath the plugin: files by path, a dated inbox folder list. */
function engine(on: On, files: Files, folders: string[] | Error = ['2026-01-03', '2026-01-10']) {
  const reads: string[] = []
  on('command.register', () => ({ value: { command: 'ledger' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('fs.list', () =>
    folders instanceof Error
      ? { deny: folders.message }
      : {
          value: folders.map(name => ({ name, kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false })),
        },
  )
  on('fs.read', (_, e) => {
    const path = e.path.replaceAll('\\', '/')
    reads.push(path)
    const file = path === OPTIONS.ledgerPath ? LEDGER : files[path]
    if (file === undefined) return { deny: `ENOENT: ${path}` }
    return file instanceof Error ? { deny: file.message } : { value: file }
  })
  return reads
}

const INBOX = `${PIECES}/2026-01-10`
const FILES: Files = {
  [`${INBOX}/index.json`]: indexText([TEAM, PUBLIC, DONE]),
  [`${INBOX}/team-1.md`]: pieceFile(frontMatterOf(TEAM)),
  [`${INBOX}/public-1.md`]: pieceFile(frontMatterOf(PUBLIC)),
  [`${INBOX}/team-2.md`]: pieceFile(frontMatterOf(DONE)),
}

const okRun = (stderr = '', exitCode = 0) => ({
  value: { exitCode, stdout: '', stderr, isStdoutTruncated: false, isStderrTruncated: false },
})

test('"Pieces to review" lists proposed pieces above the thread lists', { options: OPTIONS }, async ($, on) => {
  const reads = engine(on, FILES)
  await $.command.run(LEDGER_COMMAND)
  // The older inbox is never read.
  expect(reads.some(p => p.includes('2026-01-03'))).toBe(false)

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })
    const headings = (await ui.findAll({ type: 'Text' })).map(t => t.text)
    const pieces = headings.findIndex(t => t.startsWith('Pieces to review (2)'))
    expect(pieces).toBeGreaterThanOrEqual(0)
    expect(pieces).toBeLessThan(headings.findIndex(t => t.startsWith('At risk, recent')))
    expect((await ui.find({ key: 'piece:2026-01-10-team-1' }))?.text).toBe('team · Piece 2026-01-10-team-1 · 0.80')
    expect(await ui.find({ key: 'piece:2026-01-10-public-1' })).toBeDefined()
    expect(await ui.find({ key: 'piece:2026-01-10-team-2' })).toBeUndefined()
    await ui.unmount()
  }
})

test('no section at all when there is no inbox', { options: OPTIONS }, async ($, on) => {
  engine(on, {}, new Error('ENOENT: no such directory'))
  await $.command.run(LEDGER_COMMAND)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ text: /Pieces to review/ })).toBeUndefined()
    expect(await ui.find({ text: /At risk, recent/ })).toBeDefined()
    await ui.unmount()
  }
})

for (const [name, files, pattern] of [
  ['a missing index.json', {}, /No index\.json in the inbox 2026-01-10/],
  ['a malformed index.json', { [`${INBOX}/index.json`]: '{"pieces": [' }, /Malformed index\.json/],
] as const) {
  test(`${name} is said in the section, and the ledger still shows`, { options: OPTIONS }, async ($, on) => {
    engine(on, files)
    await $.command.run(LEDGER_COMMAND)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ ...PANE, surface })
      expect(await ui.find({ text: /^Pieces to review/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: pattern })).toBeDefined()
      expect(await ui.find({ key: 'risk:r1' })).toBeDefined()
      await ui.unmount()
    }
  })
}

test('a piece shows summary, rationale and source titles from the ledger', { options: OPTIONS }, async ($, on) => {
  engine(on, FILES)
  await $.command.run(LEDGER_COMMAND)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })
    await ui.press({ key: 'piece:2026-01-10-team-1' })
    expect(await ui.find({ text: /Summary of 2026-01-10-team-1/ })).toBeDefined()
    expect(await ui.find({ text: /Rationale of 2026-01-10-team-1/ })).toBeDefined()
    expect(await ui.find({ text: /Ledger title r1/ })).toBeDefined()
    expect(await ui.find({ text: /Index title gone/ })).toBeDefined()
    expect(await ui.find({ text: /Index title r1/ })).toBeUndefined()
    expect(await ui.find({ key: 'approve' })).toBeDefined()
    expect(await ui.find({ key: 'discard' })).toBeDefined()
    expect(await ui.find({ text: /Check it for internal details before approving\./ })).toBeUndefined()
    await ui.press({ key: 'back' })
    await ui.press({ key: 'piece:2026-01-10-public-1' })
    expect(await ui.find({ text: /Check it for internal details before approving\./ })).toBeDefined()
    await ui.press({ key: 'back' })
    expect(await ui.find({ text: /^Pieces to review/ })).toBeDefined()
    await ui.unmount()
  }
})

test('Approve runs the CLI on a timer, then toasts and re-reads the inbox', { options: OPTIONS }, async ($, on) => {
  const files: Files = { ...FILES }
  const reads = engine(on, files)
  const clock = mock.clock(on)
  const runs: unknown[] = []
  const toasts: string[] = []
  on('process.run', async (_, e) => {
    runs.push({ argv: e.argv, init: e.init })
    await clock.sleep(30_000)
    // The CLI marks the piece approved in the index.
    files[`${INBOX}/index.json`] = indexText([{ ...TEAM, status: 'approved' }, PUBLIC, DONE])
    files[`${INBOX}/team-1.md`] = pieceFile({ ...frontMatterOf(TEAM), status: 'approved' })
    return okRun()
  })
  on('ui.toast', (_, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  await $.command.run(LEDGER_COMMAND)
  const indexReads = () => reads.filter(p => p.endsWith('/index.json')).length
  expect(indexReads()).toBe(1)

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'piece:2026-01-10-team-1' })
  // The press returns with the clock standing still.
  await ui.press({ key: 'approve' })
  expect((await ui.find({ key: 'approve' }))?.text).toBe('Approving…')
  await clock.settle()
  expect(runs).toEqual([
    {
      argv: ['py-fixture', '-m', 'work_ledger', 'pieces', 'approve', '2026-01-10-team-1'],
      init: { cwd: ROOT, env: { PYTHONPATH: 'src' }, timeoutMs: 120000 },
    },
  ])
  // A second press while it runs starts nothing.
  await ui.press({ key: 'discard' })
  await clock.settle()
  expect(runs).toHaveLength(1)

  await clock.advance(30_000)
  expect(toasts).toEqual(['Piece approved.'])
  expect(indexReads()).toBe(2)
  expect(await ui.find({ key: 'approve' })).toBeUndefined()
  expect((await ui.find({ text: /^Pieces to review/ }))?.text).toMatch(/\(1\)/)
  await ui.unmount()
})

test('a refused Approve toasts the last stderr line and re-reads the inbox', { options: OPTIONS }, async ($, on) => {
  const reads = engine(on, FILES)
  const clock = mock.clock(on)
  const toasts: string[] = []
  let runs = 0
  on('process.run', () => {
    runs++
    return runs === 1
      ? okRun('Traceback\nrefused: the public piece failed the check (rule: url)\n', 1)
      : { deny: 'spawn py-fixture ENOENT' }
  })
  on('ui.toast', (_, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  await $.command.run(LEDGER_COMMAND)

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  await ui.press({ key: 'piece:2026-01-10-public-1' })
  await ui.press({ key: 'approve' })
  await clock.settle()
  await ui.press({ key: 'discard' })
  await clock.settle()
  expect(toasts).toEqual([
    'Approve failed (exit 1): refused: the public piece failed the check (rule: url)',
    expect.stringMatching(/^Discard failed: .*ENOENT/),
  ])
  expect(reads.filter(p => p.endsWith('/index.json')).length).toBe(3)
  // The piece is still proposed, so its detail stays open.
  expect((await ui.find({ key: 'approve' }))?.text).toBe('Approve')
  await ui.unmount()
})
