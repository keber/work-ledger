import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register, RenderChildren } from 'claude-code'

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
  clip,
  expandHome,
  fitList,
  formatAge,
  formatCounts,
  formatDays,
  formatRisk,
  lastLine,
  parseLedger,
  planSections,
  projectRows,
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
const PUBLIC_WARNING = 'Check it for internal details before approving.'

// Change a shape tag when the stored value's fields change: an older value is
// then read as the initial one instead of being misread.
const ledger = atom({ plugin: 'work-ledger', key: 'ledger' } as const, { status: 'unloaded' } as LedgerLoad, {
  shape: 'ledger-1',
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
    const { Box, Text, Button } = $.ui.resolve(e)
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

    const refreshButton = (
      <Button key="refresh" variant="primary" onPress={() => (isRunning ? undefined : startRefresh($, cfg))}>
        {isRunning ? 'Refreshing…' : 'Refresh'}
      </Button>
    )
    const select = (id: string | null) => () => update($, selected, () => id)
    const toggle = (projectId: string) => () =>
      update($, expanded, list =>
        list.includes(projectId) ? list.filter(id => id !== projectId) : [...list, projectId],
      )
    const more = (n: number) => (n > 0 ? [<Text dimColor>{`+${n} more`}</Text>] : [])

    if (load.status !== 'ok') {
      const message =
        load.status === 'unloaded' ? 'The ledger is not loaded yet.' : load.error.message
      return (
        <Box flexDirection="column">
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

    // List view. Rows on the terminal: 2 for the header, then per section one
    // for its top margin and one for its heading; the rest is shared. A section
    // the person expanded takes all its rows and the pane body scrolls.
    const shownAll = await read($, showAll)
    const byProject = projectRows(view, expandedIds)
    const isAll = (id: LedgerSection) => shownAll.includes(id)
    // The pieces section is drawn only when the inbox has something to say:
    // proposed pieces, or an index it could not read.
    const hasPieces = toReview.length > 0 || inbox.status === 'error'
    const pieceItems = inbox.status === 'error' ? [] : toReview
    const [pieceRows = 0, riskRows = 0, projRows = 0, openRows = 0, allRows = 0] = planSections(
      // Its margin and heading, plus up to two rows for an error note.
      rows - 10 - (hasPieces ? 2 + (inbox.status === 'error' ? 2 : 0) : 0),
      [
      { count: hasPieces ? pieceItems.length : 0, isExpanded: hasPieces && isAll('pieces') },
      { count: view.atRiskRecent.length, isExpanded: isAll('risk') },
      { count: view.projectsAtRisk.length, isExpanded: isAll('projects') },
      { count: view.open.length, isExpanded: isAll('open') },
      { count: byProject.length, isExpanded: isAll('all') },
      ],
    )

    const setAll = (id: LedgerSection, isShown: boolean) => () =>
      update($, showAll, list => (isShown ? [...list.filter(s => s !== id), id] : list.filter(s => s !== id)))
    const heading = (text: string) => <Text bold>{clip(text, cols)}</Text>
    const item = (key: string, onPress: () => unknown, name: string, data: string) => {
      const [n, d] = splitClip(name, data, cols)
      return (
        <Button key={key} plain onPress={onPress}>
          <Text size="footnote">{n}</Text>
          <Text size="footnote" dimColor>
            {d}
          </Text>
        </Button>
      )
    }
    const threadItem = (prefix: string, t: LedgerThreadView, name: string, data: string) =>
      item(`${prefix}:${t.id}`, select(t.id), name, data)

    function section<T>(
      id: LedgerSection,
      title: string,
      items: readonly T[],
      rowsFor: number,
      draw: (x: T) => RenderChildren,
      note: string | null = null,
    ) {
      const fit = isAll(id) ? { shown: [...items], more: 0 } : fitList(items, rowsFor)
      return (
        <Box flexDirection="column" marginTop="md" rowGap="xs">
          {heading(title)}
          {note === null ? [] : [<Text color="error">{clip(note, cols * 2)}</Text>]}
          {fit.shown.map(draw)}
          {fit.more > 0
            ? [
                <Button key={`more:${id}`} plain dimColor onPress={setAll(id, true)}>
                  {`+${fit.more} more`}
                </Button>,
              ]
            : []}
          {isAll(id)
            ? [
                <Button key={`less:${id}`} plain dimColor onPress={setAll(id, false)}>
                  Show less
                </Button>,
              ]
            : []}
        </Box>
      )
    }
    const { counts } = view

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" justifyContent="space-between">
          <Text dimColor>{clip(`Updated ${formatAge(view.generatedAt, now)}`, cols - 14)}</Text>
          {refreshButton}
        </Box>
        <Text>
          {clip(
            `${counts.projectsAtRisk} projects at risk · ${counts.threadsAtRisk} threads at risk · ${counts.open} open`,
            cols,
          )}
        </Text>

        {hasPieces
          ? [
              section(
                'pieces',
                `Pieces to review (${pieceItems.length})`,
                pieceItems,
                pieceRows,
                p =>
                  item(
                    `piece:${p.id}`,
                    selectPiece(p.id),
                    `${p.audience} · ${p.title}`,
                    ` · ${formatRelevance(p.relevance)}`,
                  ),
                inbox.status === 'error' ? inbox.message : null,
              ),
            ]
          : []}

        {section('risk', `At risk, recent (${view.atRiskRecent.length})`, view.atRiskRecent, riskRows, id => {
          const t = view.threads[id]!
          return threadItem(
            'risk',
            t,
            `${t.projectName} · ${t.title}`,
            ` · ${formatDays(t.daysIdle)} · ${formatRisk(t.risk, t.notOnRemote)}`,
          )
        })}

        {section('projects', `Projects at risk (${view.projectsAtRisk.length})`, view.projectsAtRisk, projRows, id => {
          const p = view.projectsById[id]!
          const older = p.oldAtRiskCount ? ` · ${p.oldAtRiskCount} older at risk` : ''
          const [n, d] = splitClip(
            p.name,
            ` · ${formatRisk(p.risk, p.notOnRemote)} · ${formatDays(p.daysIdle)}${older}`,
            cols,
          )
          return (
            <Text size="footnote">
              {n}
              <Text dimColor>{d}</Text>
            </Text>
          )
        })}

        {section(
          'open',
          view.counts.open > view.open.length
            ? `Open (${view.open.length} of ${view.counts.open})`
            : `Open (${view.counts.open})`,
          view.open,
          openRows,
          id => {
            const t = view.threads[id]!
            return threadItem('open', t, `${t.projectName} · ${t.title}`, ` · ${formatDays(t.daysIdle)}`)
          },
        )}

        {section('all', `By project (${view.projects.length})`, byProject, allRows, row => {
          if (row.kind === 'project') {
            const p = view.projectsById[row.projectId]!
            return item(
              `project:${p.id}`,
              toggle(p.id),
              `${row.isExpanded ? '▾' : '▸'} ${p.name}`,
              ` · ${formatCounts(p.counts)}`,
            )
          }
          const t = view.threads[row.threadId]!
          return threadItem(
            `in:${row.projectId}`,
            t,
            `   ${t.title}`,
            ` · ${t.effectiveState} · ${formatDays(t.daysIdle)}`,
          )
        })}
      </Box>
    )

    function renderPiece(p: PieceView) {
      const isBusy = action.id !== null && Date.now() - action.startedAt < STALE_PIECE_MS
      const busyLabel = (kind: PieceActionKind, idle: string, running: string) =>
        isBusy && action.id === p.id && action.action === kind ? running : idle
      const ledgerTitles = Object.fromEntries(Object.values(view.threads).map(t => [t.id, t.title]))
      const sources = fitList(sourceTitles(p, ledgerTitles), 5)
      const textWidth = 3 * Math.max(10, cols - 8)
      const field = (label: string, value: string | null) => (
        <Text>
          <Text dimColor>{`${label}: `}</Text>
          {value ? clip(value, textWidth) : '—'}
        </Text>
      )
      const press = (kind: PieceActionKind) => () =>
        isBusy ? undefined : startPieceAction($, cfg, p.id, kind)

      return (
        <Box flexDirection="column" rowGap="xs">
          <Box flexDirection="row" gap={1}>
            <Button key="back" role="dismiss" onPress={selectPiece(null)}>
              Back
            </Button>
          </Box>
          <Text bold>{clip(p.title, cols * 2)}</Text>
          <Text dimColor>
            {clip(`${p.audience} · ${p.visibility} · relevance ${formatRelevance(p.relevance)} · ${p.id}`, cols)}
          </Text>
          {p.visibility === 'external' || p.audience === 'public'
            ? [<Text color="warning">{PUBLIC_WARNING}</Text>]
            : []}
          {p.problem ? [<Text color="error">{clip(p.problem, cols * 2)}</Text>] : []}
          {field('Summary', p.summary)}
          {field('Rationale', p.rationale)}
          <Text dimColor>{`Source threads (${p.sourceThreadIds.length})`}</Text>
          {sources.shown.map(title => (
            <Text size="footnote">{clip(`  ${title}`, cols)}</Text>
          ))}
          {more(sources.more)}
          <Box flexDirection="row" gap={1}>
            <Button key="approve" variant="primary" onPress={press('approve')}>
              {busyLabel('approve', 'Approve', 'Approving…')}
            </Button>
            <Button key="discard" onPress={press('discard')}>
              {busyLabel('discard', 'Discard', 'Discarding…')}
            </Button>
          </Box>
        </Box>
      )
    }

    function renderDetail(t: LedgerThreadView) {
      const related = t.related.map(id => view.threads[id]!).filter(Boolean)
      const sessionFit = fitList(t.sessions, 3)
      const relatedFit = fitList(related, 3)
      // Rows left for the three free texts once the fixed lines are drawn.
      const fixed = 10 + (t.note ? 1 : 0) + Math.min(t.sessions.length, 3) + Math.min(related.length, 3)
      const linesEach = Math.min(6, Math.max(1, Math.floor((rows - fixed) / 3)))
      const textWidth = linesEach * Math.max(10, cols - 8)
      const field = (label: string, value: string | null) => (
        <Text>
          <Text dimColor>{`${label}: `}</Text>
          {value ? clip(value, textWidth) : '—'}
        </Text>
      )
      const resume = t.lead ? `claude --resume ${t.lead}` : null
      const stateText = t.state
        ? `${t.effectiveState} (override)${t.suggestedReason ? ` · suggested: ${t.suggestedReason}` : ''}`
        : `${t.effectiveState}${t.suggestedReason ? ` · ${t.suggestedReason}` : ''}`
      const lastAt = t.lastAt ? t.lastAt.slice(0, 16).replace('T', ' ') : 'unknown'

      return (
        <Box flexDirection="column">
          <Box flexDirection="row" gap={1}>
            <Button key="back" role="dismiss" onPress={select(null)}>
              Back
            </Button>
          </Box>
          <Text bold>{clip(t.title, cols * 2)}</Text>
          <Text>{clip(`${t.projectName} · ${t.key}`, cols)}</Text>
          <Text>{clip(`State: ${stateText}`, cols)}</Text>
          {t.note ? [<Text>{clip(`Note: ${t.note}`, cols)}</Text>] : []}
          <Text>{clip(`Last activity: ${lastAt} · ${formatDays(t.daysIdle)} idle`, cols)}</Text>
          {field('Recap', t.recap)}
          {field('Ask', t.ask)}
          {field('Last prompt', t.lastPrompt)}
          <Text dimColor>{`Sessions (${t.sessions.length})`}</Text>
          {sessionFit.shown.map(id => (
            <Text>{clip(`  ${id}${id === t.lead ? ' (lead)' : ''}`, cols)}</Text>
          ))}
          {more(sessionFit.more)}
          {resume
            ? [
                <Box flexDirection="row" justifyContent="space-between">
                  <Text>{clip(resume, cols - 8)}</Text>
                  <Button key="copy" plain onPress={press => $.ui.copy({ text: resume, surface: press.surface })}>
                    Copy
                  </Button>
                </Box>,
              ]
            : [<Text dimColor>No session to resume.</Text>]}
          <Text dimColor>{`Related (${related.length})`}</Text>
          {relatedFit.shown.map(r => (
            <Button key={`related:${r.id}`} plain onPress={select(r.id)}>
              {clip(`  ${r.projectName} · ${r.title} · ${r.effectiveState}`, cols)}
            </Button>
          ))}
          {more(relatedFit.more)}
        </Box>
      )
    }
  })
}
