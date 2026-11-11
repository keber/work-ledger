import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register, RenderChildren, ThemeKey } from 'claude-code'

import type {
  LedgerLoad,
  LedgerSection,
  LedgerThreadView,
  PieceAction,
  PieceActionKind,
  PiecesLoad,
  PieceView,
} from '../types'
import {
  buildPieces,
  formatRelevance,
  isSafePieceFile,
  isSafePieceId,
  latestInbox,
  parseFrontMatter,
  parseIndex,
  proposedPieces,
  sourceTitles,
} from './pieces'
import type { FrontMatterResult } from './pieces'
import {
  ACCENT,
  CARD_BORDER,
  BADGE,
  COLD,
  ROW_HOVER,
  STATUS_MARK,
  UNPUSHED_BG,
  cells,
  percent,
  riskFacts,
  riskIndicators,
  stackSegments,
  barSvg,
  statusKey,
} from './style'
import type { Indicators } from './style'
import { legendOf, paletteFor, stateFill } from './palette'
import {
  clip,
  expandHome,
  fitList,
  formatAge,
  formatDays,
  lastLine,
  parseLedger,
  readError,
  splitClip,
} from './view-model'

const PANE = 'work-ledger'
const TITLE = 'Work ledger'
const REFRESH_TIMEOUT_MS = 600_000
// A run older than this is from a module that reloaded mid-refresh: ignore it.
const STALE_RUN_MS = REFRESH_TIMEOUT_MS + 60_000

// A leading `~` is the user's home dir, expanded at runtime (see resolveConfig).
const DEFAULTS = {
  ledgerPath: '~/Proyectos/work-ledger/out/ledger.json',
  projectRoot: '~/Proyectos/work-ledger',
  pythonCommand: 'python',
  piecesDir: '~/Proyectos/work-ledger/out/pieces/inbox',
}
const PIECE_TIMEOUT_MS = 120_000
const STALE_PIECE_MS = PIECE_TIMEOUT_MS + 60_000
/** Cells across a per-project stacked bar (desktop only). */
const BAR_CELLS = 10
/** The desktop bar: an Svg this many CSS px across and down, inside the BAR_CELLS slot. */
const BAR_PX = 64
const BAR_PX_HIGH = 6
/** Cells of the right-aligned thread-count slot of a project row. */
const COUNT_CELLS = 3
/** Items a collapsed section shows before its "Show N more" link. */
const COLLAPSED_ITEMS = 3
/** The expanded-ids entry of the "repos without sessions" group. */
const NO_SESSIONS = '(no-sessions)'
const NO_INDICATORS: Indicators = { isUnpushed: false, badges: [], warnings: [] }
const PUBLIC_WARNING = 'Check it for internal details before approving.'

// Change a shape tag when the stored value's fields change: an older value is
// then read as the initial one instead of being misread.
const ledger = atom({ plugin: 'work-ledger', key: 'ledger' } as const, { status: 'unloaded' } as LedgerLoad, {
  shape: 'ledger-2',
})
const selected = atom({ plugin: 'work-ledger', key: 'selected' } as const, null as string | null, {
  shape: 'selected-1',
})
const expanded = atom({ plugin: 'work-ledger', key: 'expanded' } as const, [] as string[], {
  shape: 'expanded-1',
})
const showAll = atom({ plugin: 'work-ledger', key: 'showAll' } as const, [] as LedgerSection[], {
  shape: 'show-all-1',
})
const refresh = atom(
  { plugin: 'work-ledger', key: 'refresh' } as const,
  { isRunning: false, startedAt: 0 },
  { shape: 'refresh-1' },
)
const pieces = atom({ plugin: 'work-ledger', key: 'pieces' } as const, { status: 'none' } as PiecesLoad, {
  shape: 'pieces-1',
})
const selectedPiece = atom({ plugin: 'work-ledger', key: 'selectedPiece' } as const, null as string | null, {
  shape: 'selected-piece-1',
})
const NO_ACTION: PieceAction = { id: null, action: null, startedAt: 0 }
const pieceAction = atom({ plugin: 'work-ledger', key: 'pieceAction' } as const, NO_ACTION, {
  shape: 'piece-action-1',
})

const option = (options: PluginOptions, name: keyof typeof DEFAULTS): string => {
  const value = options[name]
  return typeof value === 'string' && value.trim() !== '' ? value : DEFAULTS[name]
}

const errorMessage = (err: unknown): string =>
  err instanceof Error ? err.message : String(err)

type Config = { ledgerPath: string; projectRoot: string; pythonCommand: string; piecesDir: string }

const usesHome = (cfg: Config): boolean => Object.values(cfg).some(v => v.startsWith('~'))

/**
 * The home dir for `~`: USERPROFILE (Windows), else HOME; undefined when neither is
 * set or the read is refused, which leaves `~` paths as they are (a read then fails
 * naming the path). The mod API has no home-dir call; `$.env.get` is its own way to
 * read the environment, so no process is started for it.
 */
async function homeDir($: EngineInterface): Promise<string | undefined> {
  try {
    return (await $.env.get('USERPROFILE')) || (await $.env.get('HOME')) || undefined
  } catch {
    return undefined
  }
}

function withHome(cfg: Config, home: string | undefined): Config {
  return {
    ledgerPath: expandHome(cfg.ledgerPath, home),
    projectRoot: expandHome(cfg.projectRoot, home),
    pythonCommand: expandHome(cfg.pythonCommand, home),
    piecesDir: expandHome(cfg.piecesDir, home),
  }
}

/** The settings with `~` expanded; the environment is read only when a setting needs it. */
async function resolveConfig($: EngineInterface, cfg: Config): Promise<Config> {
  return usesHome(cfg) ? withHome(cfg, await homeDir($)) : cfg
}

/**
 * Reads the latest curation inbox: the newest YYYY-MM-DD folder of piecesDir,
 * its index.json and each listed piece's front matter. No inbox at all is
 * `none` (the section is not drawn); an unreadable or malformed index is an
 * error the section shows.
 */
async function loadPieces($: EngineInterface, cfg: Config): Promise<void> {
  const next = await readInbox($, cfg)
  await update($, pieces, () => next)
}

async function readInbox($: EngineInterface, cfg: Config): Promise<PiecesLoad> {
  const root = cfg.piecesDir.replace(/[\\/]+$/, '')
  let date: string | null
  try {
    date = latestInbox(await $.fs.list(root))
  } catch {
    return { status: 'none' }
  }
  if (date === null) return { status: 'none' }
  const dir = `${root}/${date}`
  let text: string
  try {
    text = await $.fs.read(`${dir}/index.json`)
  } catch (err) {
    return { status: 'error', date, message: `No index.json in the inbox ${date}: ${errorMessage(err)}` }
  }
  const index = parseIndex(text)
  if (!index.ok) return { status: 'error', date, message: index.message }
  const frontMatters: Record<string, FrontMatterResult | undefined> = {}
  for (const entry of index.entries) {
    const file = typeof entry === 'object' && entry !== null ? (entry as { file?: unknown }).file : undefined
    if (typeof file !== 'string' || !isSafePieceFile(file) || file in frontMatters) continue
    try {
      frontMatters[file] = parseFrontMatter(await $.fs.read(`${dir}/${file}`))
    } catch {
      frontMatters[file] = undefined
    }
  }
  return { status: 'ok', date, pieces: buildPieces(index.entries, frontMatters) }
}

/**
 * What an Approve or Discard press runs: marks the action as running and hands
 * the CLI run to a `$.clock.after` timer, as Refresh does, so the press returns
 * at once.
 */
async function startPieceAction(
  $: EngineInterface,
  cfg: Config,
  id: string,
  action: PieceActionKind,
): Promise<void> {
  if (!isSafePieceId(id)) {
    $.ui.toast('Refusing a piece id that is not plain letters, digits and hyphens.')
    return
  }
  let isStarted = false
  await update($, pieceAction, current => {
    isStarted = false
    if (current.id !== null && Date.now() - current.startedAt < STALE_PIECE_MS) return current
    isStarted = true
    return { id, action, startedAt: Date.now() }
  })
  if (!isStarted) return
  $.clock.after(0, () => {
    runPieceAction($, cfg, id, action).catch(err =>
      $.ui.log(`work-ledger pieces ${action}: ${errorMessage(err)}`, { to: 'debug' }),
    )
  })
}

async function runPieceAction(
  $: EngineInterface,
  cfg: Config,
  id: string,
  action: PieceActionKind,
): Promise<void> {
  const verb = action === 'approve' ? 'Approve' : 'Discard'
  try {
    const result = await $.process.run([cfg.pythonCommand, '-m', 'work_ledger', 'pieces', action, id], {
      cwd: cfg.projectRoot,
      env: { PYTHONPATH: 'src' },
      timeoutMs: PIECE_TIMEOUT_MS,
    })
    if (result.exitCode === 0) {
      await update($, selectedPiece, current => (current === id ? null : current))
      $.ui.toast(action === 'approve' ? 'Piece approved.' : 'Piece discarded.')
    } else {
      const line = lastLine(result.stderr)
      $.ui.toast(`${verb} failed (exit ${result.exitCode})${line ? `: ${line}` : '.'}`, { timeoutMs: 10_000 })
    }
  } catch (err) {
    $.ui.toast(`${verb} failed: ${errorMessage(err)}`, { timeoutMs: 10_000 })
  } finally {
    await update($, pieceAction, () => NO_ACTION)
    await loadPieces($, cfg)
  }
}

async function loadLedger($: EngineInterface, cfg: Config): Promise<void> {
  let next: LedgerLoad
  try {
    const text = await $.fs.read(cfg.ledgerPath)
    const parsed = parseLedger(text)
    next = parsed.ok ? { status: 'ok', view: parsed.view } : { status: 'error', error: parsed.error }
  } catch (err) {
    next = { status: 'error', error: readError(cfg.ledgerPath, err) }
  }
  await update($, ledger, () => next)
}

/**
 * What the Refresh press runs: marks the refresh as running and hands the run
 * to a `$.clock.after` timer, the reference's mechanism for work that outlives
 * a dispatch, so the press returns at once (a run takes minutes; a press hook
 * has a 10 s budget).
 */
async function startRefresh($: EngineInterface, cfg: Config): Promise<void> {
  let isStarted = false
  await update($, refresh, current => {
    isStarted = false
    if (current.isRunning && Date.now() - current.startedAt < STALE_RUN_MS) return current
    isStarted = true
    return { isRunning: true, startedAt: Date.now() }
  })
  if (!isStarted) return
  $.clock.after(0, () => {
    runRefresh($, cfg).catch(err => $.ui.log(`work-ledger refresh: ${errorMessage(err)}`, { to: 'debug' }))
  })
}

/** The refresh run itself, on the timer: never inside a press dispatch. */
async function runRefresh($: EngineInterface, cfg: Config): Promise<void> {
  try {
    const result = await $.process.run([cfg.pythonCommand, '-m', 'work_ledger', 'refresh'], {
      cwd: cfg.projectRoot,
      env: { PYTHONPATH: 'src' },
      timeoutMs: REFRESH_TIMEOUT_MS,
    })
    if (result.exitCode === 0) {
      await loadLedger($, cfg)
      await loadPieces($, cfg)
      $.ui.toast('Ledger refreshed.')
    } else {
      const line = lastLine(result.stderr)
      $.ui.toast(`Refresh failed (exit ${result.exitCode})${line ? `: ${line}` : '.'}`, {
        timeoutMs: 10_000,
      })
    }
  } catch (err) {
    $.ui.toast(`Refresh failed: ${errorMessage(err)}`, { timeoutMs: 10_000 })
  } finally {
    await update($, refresh, () => ({ isRunning: false, startedAt: 0 }))
  }
}

async function openPane($: EngineInterface, cfg: Config): Promise<void> {
  await loadLedger($, cfg)
  await loadPieces($, cfg)
  await $.ui.open({ id: PANE, title: TITLE })
}

export const register: Register = (on, options) => {
  const configured: Config = {
    ledgerPath: option(options, 'ledgerPath'),
    projectRoot: option(options, 'projectRoot'),
    pythonCommand: option(options, 'pythonCommand'),
    piecesDir: option(options, 'piecesDir'),
  }
  // Fills only; text keeps theme keys. `auto` is the universal palette.
  const { palette } = paletteFor(typeof options.colorScheme === 'string' ? options.colorScheme : 'auto')

  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'ledger', description: 'Show the work ledger pane' })
    if (options.openOnStart === true) {
      const cfg = await resolveConfig($, configured)
      // Reading the ledger is quick; the open is not awaited, as a pane opened at start is not.
      await loadLedger($, cfg)
      await loadPieces($, cfg)
      void $.ui.open({ id: PANE, title: TITLE })
    }
    return next(e)
  })

  on('command.run', { command: 'ledger' }, async $ => {
    await openPane($, await resolveConfig($, configured))
    return { text: 'Work ledger pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const elements = $.ui.resolve(e)
    const { Box, Text, Button } = elements
    // The terminal's table has no Svg: its bar stays a row of Boxes.
    const Svg = 'Svg' in elements ? elements.Svg : undefined
    const cfg = await resolveConfig($, configured)
    const load = await read($, ledger)
    const selectedId = await read($, selected)
    const expandedIds = await read($, expanded)
    const refreshState = await read($, refresh)
    const inbox = await read($, pieces)
    const selectedPieceId = await read($, selectedPiece)
    const action = await read($, pieceAction)

    const now = Date.now()
    const cols = Math.max(20, e.props.bodyColumns - 1)
    const rows = Math.max(10, e.props.scroll.bodyRows || (e.viewport?.rows ?? 30) - 4)
    const isRunning = refreshState.isRunning && now - refreshState.startedAt < STALE_RUN_MS
    // The terminal draws one text size and no bars; everything else degrades in place.
    const isTerminal = e.surface === 'terminal'
    const rowHover = isTerminal ? ROW_HOVER : palette.fills.paused

    const refreshButton = (
      <Button key="refresh" variant="secondary" onPress={() => (isRunning ? undefined : startRefresh($, cfg))}>
        {isRunning ? 'Refreshing…' : 'Refresh'}
      </Button>
    )
    const select = (id: string | null) => () => update($, selected, () => id)
    const toggle = (projectId: string) => () =>
      update($, expanded, list =>
        list.includes(projectId) ? list.filter(id => id !== projectId) : [...list, projectId],
      )

    // Type scale, three sizes: caption for section labels, body for titles,
    // footnote for metadata. Every number is tabular.
    const label = (text: string) => (
      <Text size="caption" dimColor tabular>
        {clip(text.toUpperCase(), cols)}
      </Text>
    )
    const note = (text: string) => (
      <Text size="caption" dimColor>
        {text}
      </Text>
    )
    const more = (n: number) => (n > 0 ? [note(`${n} more`)] : [])

    if (load.status !== 'ok') {
      const message =
        load.status === 'unloaded' ? 'The ledger is not loaded yet.' : load.error.message
      return (
        <Box flexDirection="column" rowGap="xs">
          <Text color={load.status === 'error' ? 'error' : undefined}>{message}</Text>
          <Box flexDirection="row" gap={1}>
            {refreshButton}
            <Button key="reload" onPress={() => Promise.all([loadLedger($, cfg), loadPieces($, cfg)])}>
              Reload
            </Button>
          </Box>
        </Box>
      )
    }

    const view = load.view
    const thread = selectedId === null ? undefined : view.threads[selectedId]

    const toReview = inbox.status === 'ok' ? proposedPieces(inbox.pieces) : []
    const piece = selectedPieceId === null ? undefined : toReview.find(p => p.id === selectedPieceId)
    const selectPiece = (id: string | null) => () => update($, selectedPiece, () => id)

    if (piece !== undefined) {
      return renderPiece(piece)
    }
    if (thread !== undefined) {
      return renderDetail(thread)
    }

    /**
     * One row anatomy everywhere: marker · name (one line, takes the room) ·
     * fixed-width indicators and days, then the row's press target. The row
     * lights on hover.
     *
     * Only a Button is pressable, and a desktop draws a Button's contents in its
     * own label style: it drops `color` (the marks turned black) and `size` (the
     * names stayed large). So everything styled sits outside the Button, and the
     * Button is a small target: "›" at the end of a thread row, the chevron at
     * the start of a project row.
     */
    type Row = {
      key: string
      /** Status mark color; absent draws no mark (project rows lead with the chevron). */
      color?: ThemeKey
      name: string
      nameColor?: ThemeKey
      isNameDim?: boolean
      indicators?: Indicators
      meta: string[]
      /** A right-aligned, fixed-width number slot, so every bar ends at the same line. */
      count?: string
      onPress?: () => unknown
      /** A project row: its chevron is the press target and leads the row. */
      chevron?: { glyph: string; color: ThemeKey }
      indent?: boolean
      extra?: RenderChildren
      extraWidth?: number
    }
    function row(r: Row) {
      const ind = r.indicators ?? NO_INDICATORS
      const warning = ind.warnings.join(' · ')
      // No hover on the terminal: the "!" text is drawn inline there.
      const isInline = isTerminal && warning !== ''
      const rightWidth =
        r.meta.reduce((sum, m) => sum + m.length + 1, 0) +
        ind.badges.length * 2 +
        (warning ? 2 : 0) +
        (isInline ? warning.length + 1 : 0) +
        (r.extraWidth ?? 0) +
        (r.count === undefined ? 0 : COUNT_CELLS + 1) +
        (r.onPress && !r.chevron ? 2 : 0)
      const room = Math.max(12, cols - rightWidth - 3 - (r.indent ? 2 : 0))
      const name = (
        <Text
          size="footnote"
          color={ind.isUnpushed && !isTerminal ? palette.unpushedText : r.nameColor}
          dimColor={r.isNameDim}
        >
          {clip(r.name, room)}
        </Text>
      )
      const lead = r.chevron
        ? [
            r.onPress ? (
              <Button key={r.key} plain onPress={r.onPress}>
                <Text color={r.chevron.color}>{r.chevron.glyph}</Text>
              </Button>
            ) : (
              <Text color={r.chevron.color}>{r.chevron.glyph}</Text>
            ),
          ]
        : r.color
          ? [
              <Text size="footnote" color={r.color}>
                {STATUS_MARK}
              </Text>,
            ]
          : []
      return (
        <Box
          key={`row:${r.key}`}
          flexDirection="row"
          justifyContent="space-between"
          alignItems="center"
          gap={1}
          paddingLeft={r.indent ? 2 : 0}
          hover={{ backgroundColor: rowHover }}
        >
          <Box flexDirection="row" gap={1} flexGrow={1} flexShrink={1} alignItems="center">
            {lead}
            <Box
              key={r.onPress || r.chevron ? undefined : r.key}
              flexDirection="row"
              flexGrow={1}
              flexShrink={1}
              backgroundColor={ind.isUnpushed ? (isTerminal ? UNPUSHED_BG : palette.unpushedBackground) : undefined}
            >
              {name}
            </Box>
          </Box>
          <Box flexDirection="row" gap={1} flexShrink={0} alignItems="center">
            {r.extra ?? []}
            {ind.badges.map(b => (
              <Text size="caption" color={BADGE}>
                {b.letter}
              </Text>
            ))}
            {warning === ''
              ? []
              : isInline
                ? [
                    <Text size="caption" dimColor>
                      !
                    </Text>,
                    <Text size="caption" dimColor tabular>
                      {warning}
                    </Text>,
                  ]
                : [reveal(`warn:${r.key}`, <Text size="caption" dimColor>!</Text>, warning)]}
            {r.meta.map(m => (
              <Text size="caption" dimColor tabular>
                {m}
              </Text>
            ))}
            {r.count === undefined
              ? []
              : [
                  <Box flexDirection="row" width={cells(COUNT_CELLS)} justifyContent="flex-end">
                    <Text size="caption" dimColor tabular>
                      {r.count}
                    </Text>
                  </Box>,
                ]}
            {r.onPress && !r.chevron
              ? [
                  <Button key={r.key} plain dimColor onPress={r.onPress}>
                    ›
                  </Button>,
                ]
              : []}
          </Box>
        </Box>
      )
    }

    /**
     * The API has no tooltip and no z-order: an overlay below the row fell
     * behind the next one. So the text is revealed in the row itself: a keyed
     * Box is a hover scope, and a hidden sibling in it (display none, hover
     * flex) appears inline beside the target while the pointer is on it.
     */
    function reveal(key: string, target: RenderChildren, text: string) {
      return (
        <Box key={key} flexDirection="row" gap={1} alignItems="center">
          <Box display="none" hover={{ display: 'flex' }}>
            <Text size="caption" dimColor tabular>
              {clip(text, Math.max(12, cols - 16))}
            </Text>
          </Box>
          {target}
        </Box>
      )
    }

    // List view. The pane body scrolls, so nothing is fitted to the viewport:
    // a collapsed section shows its first few items and a "Show N more" link
    // on its label row; an expanded one shows them all.
    const shownAll = await read($, showAll)
    const isAll = (id: LedgerSection) => shownAll.includes(id)
    const firstOf = <T,>(id: LedgerSection, items: readonly T[]) => (isAll(id) ? [...items] : items.slice(0, COLLAPSED_ITEMS))
    const hasPieces = inbox.status !== 'none'
    const pieceItems = inbox.status === 'ok' ? toReview : []

    const setAll = (id: LedgerSection, isShown: boolean) => () =>
      update($, showAll, list => (isShown ? [...list.filter(s => s !== id), id] : list.filter(s => s !== id)))
    const link = (key: string, text: string, onPress: () => unknown) => (
      <Button key={key} plain dimColor onPress={onPress}>
        {text}
      </Button>
    )

    function section(s: {
      id: LedgerSection
      title: string
      /** Items the section holds; "Show N more" counts past COLLAPSED_ITEMS. */
      count: number
      body: RenderChildren[]
      empty: string
      intro?: RenderChildren
      error?: string | null
      isCard?: boolean
    }) {
      const hidden = isAll(s.id) ? 0 : Math.max(0, s.count - COLLAPSED_ITEMS)
      // "Show N more" and "Show less" sit on the label row: no row of their own.
      const toggle =
        hidden > 0
          ? [link(`more:${s.id}`, `Show ${hidden} more`, setAll(s.id, true))]
          : isAll(s.id) && s.count > COLLAPSED_ITEMS
            ? [link(`less:${s.id}`, 'Show less', setAll(s.id, false))]
            : []
      const body = [
        <Box flexDirection="row" justifyContent="space-between" alignItems="center" gap={1}>
          {label(s.title)}
          {toggle}
        </Box>,
        ...(s.intro ? [s.intro] : []),
        ...(s.error ? [<Text color="error">{clip(s.error, cols * 2)}</Text>] : []),
        ...(!s.error && s.count === 0 ? [note(s.empty)] : []),
        ...s.body,
      ]
      // Cards only where they mean something: the pieces section and the detail views.
      return s.isCard ? (
        <Box
          key={`card:${s.id}`}
          flexDirection="column"
          marginTop="md"
          rowGap="xs"
          borderStyle="round"
          borderColor={CARD_BORDER}
          paddingX={1}
        >
          {body}
        </Box>
      ) : (
        <Box flexDirection="column" marginTop="md" rowGap="xs">
          {body}
        </Box>
      )
    }

    const stat = (n: number, text: string, tone?: ThemeKey) => (
      <Text>
        <Text size="footnote" tabular color={n > 0 ? tone : undefined}>
          {String(n)}
        </Text>
        <Text size="caption" dimColor>{` ${text}`}</Text>
      </Text>
    )
    const days = (d: number | null): string => formatDays(d)
    const { counts } = view

    // By project: projects with sessions first; inventory-only repos (no
    // threads) behind one row. Their risk stays in "Projects at risk".
    const withThreads = view.projects.filter(id => view.projectsById[id]!.threadIds.length > 0)
    const withoutThreads = view.projects.filter(id => view.projectsById[id]!.threadIds.length === 0)
    const isNoSessionsOpen = expandedIds.includes(NO_SESSIONS)

    /** A repo the inventory knows but no session touched: listed, dim, not expandable. */
    function repoRow(id: string) {
      const p = view.projectsById[id]!
      return row({
        key: `repo:${p.id}`,
        name: p.name,
        isNameDim: true,
        indicators: riskIndicators(p.risk, p.notOnRemote),
        meta: [days(p.daysIdle)],
        indent: true,
      })
    }

    function projectRow(id: string) {
      const p = view.projectsById[id]!
      const isOpen = expandedIds.includes(p.id)
      const segments = stackSegments(p.counts)
      const worst = p.atRisk ? 'error' : (segments[0] ? statusKey(segments[0].state, null) : 'inactive')
      const summary = segments.map(s => `${s.count} ${s.state}`).join(' · ')
      // A fixed slot, so every bar starts and ends on the same vertical line.
      // Hover swaps the bar for the counts: hover can only reveal (display
      // flex), never hide, so the counts are a later sibling drawn over the bar
      // at top 0 of its own slot, on the row's hover color. They stay in the row:
      // nothing reaches the next one. Their nearest keyed Box is the row, so the
      // whole row's hover shows them.
      const bar =
        segments.length === 0 ? null : (
          <Box flexDirection="row" width={cells(BAR_CELLS)} height={1} alignItems="center">
            {Svg && !isTerminal ? (
              <Svg
                source={barSvg(
                  segments.map(s => ({ value: s.count, fill: palette.fills[stateFill(s.state)] })),
                  BAR_PX,
                  BAR_PX_HIGH,
                )}
                alt={summary}
                width={BAR_PX}
                height={BAR_PX_HIGH}
              />
            ) : (
              <Box flexDirection="row" width={cells(BAR_CELLS)} height={1}>
                {segments
                  .filter(s => s.percent > 0)
                  .map(s => (
                    <Box width={percent(s.percent)} height={1} backgroundColor={s.fill} />
                  ))}
              </Box>
            )}
            {isTerminal
              ? []
              : [
                  <Box
                    position="absolute"
                    top={0}
                    right={0}
                    display="none"
                    hover={{ display: 'flex' }}
                    backgroundColor={rowHover}
                  >
                    <Text size="caption" dimColor tabular>
                      {clip(summary, Math.max(BAR_CELLS, Math.floor(cols / 2)))}
                    </Text>
                  </Box>,
                ]}
          </Box>
        )
      const head = row({
        key: `project:${p.id}`,
        name: p.name,
        chevron: { glyph: isOpen ? '▾' : '▸', color: worst },
        meta: [],
        count: `${p.threadIds.length}`,
        onPress: toggle(p.id),
        // Rows without a bar keep its room, so the counts still line up.
        extra: bar ?? <Box width={cells(BAR_CELLS)} height={1} />,
        extraWidth: BAR_CELLS + 1,
      })
      if (!isOpen) return [head]
      return [
        head,
        ...p.threadIds.map(tid => {
          const t = view.threads[tid]!
          return row({
            key: `in:${p.id}:${t.id}`,
            color: statusKey(t.effectiveState, t.daysIdle),
            name: t.title,
            indicators: riskIndicators(t.risk, t.notOnRemote),
            meta: [t.effectiveState, days(t.daysIdle)],
            onPress: select(t.id),
            indent: true,
          })
        }),
      ]
    }

    const legend = isTerminal ? null : (
      <Box flexDirection="row" flexWrap="wrap" columnGap="sm">
        {legendOf(palette).map(l => (
          <Box flexDirection="row" gap={1} alignItems="center">
            <Text backgroundColor={l.fill}>{'  '}</Text>
            <Text size="caption" dimColor>
              {l.label}
            </Text>
          </Box>
        ))}
      </Box>
    )

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" flexWrap="wrap" columnGap="sm" justifyContent="space-between">
          {stat(view.atRiskRecent.length, 'at risk', 'error')}
          {stat(counts.goingCold, 'going cold', COLD)}
          {stat(counts.unbacked, 'no backup')}
          {stat(toReview.length, 'to review')}
        </Box>
        <Box flexDirection="row" justifyContent="space-between" alignItems="center">
          <Text size="caption" dimColor>
            {clip(`Updated ${formatAge(view.generatedAt, now)}`, cols - 14)}
          </Text>
          <Button key="refresh" plain dimColor onPress={() => (isRunning ? undefined : startRefresh($, cfg))}>
            {isRunning ? 'Refreshing…' : 'Refresh'}
          </Button>
        </Box>

        {hasPieces
          ? [
              section({
                id: 'pieces',
                title: `Pieces to review · ${pieceItems.length}`,
                count: pieceItems.length,
                empty: 'No pieces to review. New drafts arrive Thursday.',
                error: inbox.status === 'error' ? inbox.message : null,
                isCard: true,
                body: firstOf('pieces', pieceItems).map(p =>
                  row({
                    key: `piece:${p.id}`,
                    color: 'inactive',
                    name: `${p.audience} · ${p.title}`,
                    meta: [formatRelevance(p.relevance)],
                    onPress: selectPiece(p.id),
                  }),
                ),
              }),
            ]
          : []}

        {section({
          id: 'risk',
          title: `At risk, recent · ${view.atRiskRecent.length}`,
          count: view.atRiskRecent.length,
          empty: 'Nothing at risk in the last 30 days.',
          body: firstOf('risk', view.atRiskRecent).map(id => {
            const t = view.threads[id]!
            return row({
              key: `risk:${t.id}`,
              color: statusKey(t.effectiveState, t.daysIdle),
              name: `${t.projectName} · ${t.title}`,
              indicators: riskIndicators(t.risk, t.notOnRemote),
              meta: [days(t.daysIdle)],
              onPress: select(t.id),
            })
          }),
        })}

        {section({
          id: 'projects',
          title: `Projects at risk · ${view.projectsAtRisk.length}`,
          count: view.projectsAtRisk.length,
          empty: 'No project at risk.',
          body: firstOf('projects', view.projectsAtRisk).map(id => {
            const p = view.projectsById[id]!
            return row({
              key: `riskproj:${p.id}`,
              color: 'error',
              name: p.name,
              indicators: riskIndicators(
                p.risk,
                p.notOnRemote,
                p.oldAtRiskCount ? [`${p.oldAtRiskCount} older at risk`] : [],
              ),
              meta: [days(p.daysIdle)],
            })
          }),
        })}

        {section({
          id: 'open',
          title:
            counts.open > view.open.length
              ? `Open · ${view.open.length} of ${counts.open}`
              : `Open · ${counts.open}`,
          count: view.open.length,
          empty: 'No open threads.',
          body: firstOf('open', view.open).map(id => {
            const t = view.threads[id]!
            return row({
              key: `open:${t.id}`,
              color: statusKey(t.effectiveState, t.daysIdle),
              name: `${t.projectName} · ${t.title}`,
              indicators: riskIndicators(t.risk, t.notOnRemote),
              meta: [days(t.daysIdle)],
              onPress: select(t.id),
            })
          }),
        })}

        {section({
          id: 'all',
          title: `By project · ${withThreads.length}`,
          count: withThreads.length,
          empty: 'No projects with sessions yet. Refresh to build the ledger.',
          intro: withThreads.length > 0 ? legend : null,
          body: [
            ...firstOf('all', withThreads).flatMap(projectRow),
            ...(withoutThreads.length === 0
              ? []
              : [
                  row({
                    key: 'project:no-sessions',
                    name: `${withoutThreads.length} repos without sessions`,
                    isNameDim: true,
                    chevron: { glyph: isNoSessionsOpen ? '▾' : '▸', color: 'inactive' },
                    meta: [],
                    onPress: toggle(NO_SESSIONS),
                  }),
                  ...(isNoSessionsOpen ? withoutThreads.map(repoRow) : []),
                ]),
          ],
        })}
      </Box>
    )

    /** A detail view: the one place besides the pieces section drawn as a card. */
    function card(children: RenderChildren) {
      return (
        <Box flexDirection="column" rowGap="xs" borderStyle="round" borderColor={CARD_BORDER} paddingX={1}>
          {children}
        </Box>
      )
    }

    function field(name: string, value: string | null, width: number) {
      return (
        <Box flexDirection="column">
          {note(name)}
          <Text size="footnote">{value ? clip(value, width) : '—'}</Text>
        </Box>
      )
    }

    function renderPiece(p: PieceView) {
      const isBusy = action.id !== null && Date.now() - action.startedAt < STALE_PIECE_MS
      const busyLabel = (kind: PieceActionKind, idle: string, running: string) =>
        isBusy && action.id === p.id && action.action === kind ? running : idle
      const ledgerTitles = Object.fromEntries(Object.values(view.threads).map(t => [t.id, t.title]))
      const sources = fitList(sourceTitles(p, ledgerTitles), 5)
      const textWidth = 3 * Math.max(10, cols - 8)
      const press = (kind: PieceActionKind) => () =>
        isBusy ? undefined : startPieceAction($, cfg, p.id, kind)

      return card([
        <Box flexDirection="row">
          <Button key="back" role="dismiss" onPress={selectPiece(null)}>
            Back
          </Button>
        </Box>,
        <Text size="body">{clip(p.title, cols * 2)}</Text>,
        <Text size="caption" dimColor tabular>
          {clip(`${p.audience} · ${p.visibility} · relevance ${formatRelevance(p.relevance)} · ${p.id}`, cols)}
        </Text>,
        ...(p.visibility === 'external' || p.audience === 'public'
          ? [<Text color="error">{PUBLIC_WARNING}</Text>]
          : []),
        ...(p.problem ? [<Text color="error">{clip(p.problem, cols * 2)}</Text>] : []),
        field('Summary', p.summary, textWidth),
        field('Rationale', p.rationale, textWidth),
        note(`Source threads · ${p.sourceThreadIds.length}`),
        ...sources.shown.map(title => <Text>{clip(`  ${title}`, cols)}</Text>),
        ...more(sources.more),
        <Box flexDirection="row" gap={1}>
          <Button key="approve" variant="primary" onPress={press('approve')}>
            {busyLabel('approve', 'Approve', 'Approving…')}
          </Button>
          <Button key="discard" variant="secondary" onPress={press('discard')}>
            {busyLabel('discard', 'Discard', 'Discarding…')}
          </Button>
        </Box>,
      ])
    }

    function renderDetail(t: LedgerThreadView) {
      const related = t.related.map(id => view.threads[id]!).filter(Boolean)
      const sessionFit = fitList(t.sessions, 3)
      const relatedFit = fitList(related, 3)
      // Rows left for the three free texts once the fixed lines are drawn.
      const fixed = 14 + (t.note ? 1 : 0) + Math.min(t.sessions.length, 3) + Math.min(related.length, 3)
      const linesEach = Math.min(6, Math.max(1, Math.floor((rows - fixed) / 3)))
      const textWidth = linesEach * Math.max(10, cols - 8)
      const resume = t.lead ? `claude --resume ${t.lead}` : null
      const lastAt = t.lastAt ? t.lastAt.slice(0, 16).replace('T', ' ') : 'unknown'
      const color = statusKey(t.effectiveState, t.daysIdle)
      const reason = t.state
        ? `override${t.suggestedReason ? ` · suggested: ${t.suggestedReason}` : ''}`
        : t.suggestedReason

      return card([
        <Box flexDirection="row">
          <Button key="back" role="dismiss" onPress={select(null)}>
            Back
          </Button>
        </Box>,
        <Text size="body">{clip(t.title, cols * 2)}</Text>,
        <Text size="caption" dimColor>
          {clip(`${t.projectName} · ${t.key}`, cols)}
        </Text>,
        <Box flexDirection="row" gap={1}>
          <Text color={color}>{`${STATUS_MARK} ${t.effectiveState}`}</Text>
          {riskFacts(t.risk, t.notOnRemote).map(fact => (
            <Text size="caption" dimColor>
              {fact}
            </Text>
          ))}
          <Text size="caption" dimColor tabular>
            {clip(`${formatDays(t.daysIdle)} idle · last ${lastAt}`, cols)}
          </Text>
        </Box>,
        ...(reason ? [note(clip(reason, cols))] : []),
        ...(t.note ? [<Text>{clip(`Note: ${t.note}`, cols)}</Text>] : []),
        field('Recap', t.recap, textWidth),
        field('Ask', t.ask, textWidth),
        field('Last prompt', t.lastPrompt, textWidth),
        note(`Sessions · ${t.sessions.length}`),
        ...sessionFit.shown.map(id => (
          <Text size="footnote" tabular>
            {clip(`  ${id}${id === t.lead ? ' (lead)' : ''}`, cols)}
          </Text>
        )),
        ...more(sessionFit.more),
        ...(resume
          ? [
              <Box flexDirection="row" justifyContent="space-between" gap={1}>
                <Text size="footnote">{clip(resume, cols - 8)}</Text>
                <Button key="copy" variant="secondary" onPress={press => $.ui.copy({ text: resume, surface: press.surface })}>
                  Copy
                </Button>
              </Box>,
            ]
          : [note('No session to resume.')]),
        note(`Related · ${related.length}`),
        ...relatedFit.shown.map(r =>
          row({
            key: `related:${r.id}`,
            color: statusKey(r.effectiveState, r.daysIdle),
            name: `${r.projectName} · ${r.title}`,
            meta: [r.effectiveState],
            onPress: select(r.id),
          }),
        ),
        ...more(relatedFit.more),
      ])
    }
  })
}
