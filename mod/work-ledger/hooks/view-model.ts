// Pure functions: ledger.json text -> view model, plus formatting and row fitting.
// No `$` here, so everything is testable with synthetic fixtures.

import type {
  LedgerError,
  LedgerProjectView,
  LedgerThreadView,
  LedgerView,
} from '../types'

export const SUPPORTED_SCHEMA_VERSION = 2
export const OPEN_LIMIT = 15
const NO_PROJECT_ID = '(none)'

export type ParseResult =
  | { ok: true; view: LedgerView }
  | { ok: false; error: LedgerError }

type Json = Record<string, unknown>

const isObject = (v: unknown): v is Json =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)
const num = (v: unknown): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null

/** Parses an ISO timestamp; Python writes microseconds, which some engines reject. */
export function toMs(iso: string | null): number | null {
  if (iso === null) return null
  const trimmed = iso.replace(/(\.\d{3})\d+/, '$1')
  const ms = Date.parse(trimmed)
  return Number.isNaN(ms) ? null : ms
}

const byLastAtDesc = (a: LedgerThreadView, b: LedgerThreadView): number =>
  (toMs(b.lastAt) ?? -Infinity) - (toMs(a.lastAt) ?? -Infinity)

/** The error shown when the ledger file cannot be read. */
export function readError(path: string, err: unknown): LedgerError {
  const reason = err instanceof Error ? err.message : String(err)
  return {
    kind: 'missing',
    message: `Cannot read ${path}: ${reason || 'unknown error'}`,
  }
}

export function parseLedger(text: string): ParseResult {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return { ok: false, error: { kind: 'malformed', message: `Malformed JSON: ${message}` } }
  }
  if (!isObject(raw)) {
    return { ok: false, error: { kind: 'invalid', message: 'The ledger is not a JSON object.' } }
  }
  if (raw.schemaVersion !== SUPPORTED_SCHEMA_VERSION) {
    return {
      ok: false,
      error: {
        kind: 'unsupported',
        message: `The ledger is from an unsupported version (schemaVersion ${JSON.stringify(
          raw.schemaVersion ?? null,
        )}; this pane reads ${SUPPORTED_SCHEMA_VERSION}).`,
      },
    }
  }
  if (!Array.isArray(raw.threads) || !Array.isArray(raw.projects)) {
    return {
      ok: false,
      error: { kind: 'invalid', message: 'The ledger has no threads or projects list.' },
    }
  }
  return { ok: true, view: buildView(str(raw.generatedAt) ?? '', raw.projects, raw.threads) }
}

function buildView(generatedAt: string, rawProjects: unknown[], rawThreads: unknown[]): LedgerView {
  const projectsById: Record<string, LedgerProjectView> = {}
  const projects: string[] = []
  for (const p of rawProjects) {
    if (!isObject(p)) continue
    const id = str(p.id)
    if (id === null || projectsById[id]) continue
    const git = isObject(p.git) ? p.git : null
    projectsById[id] = {
      id,
      name: str(p.name) ?? id,
      atRisk: p.atRisk === true,
      risk: git ? str(git.risk) : null,
      notOnRemote: git ? num(git.notOnRemote) : null,
      daysIdle: num(p.daysIdle),
      threadIds: [],
      counts: {},
      oldAtRiskCount: 0,
    }
    projects.push(id)
  }

  const threads: Record<string, LedgerThreadView> = {}
  const order: string[] = []
  for (const t of rawThreads) {
    if (!isObject(t)) continue
    const id = str(t.id)
    if (id === null || threads[id]) continue
    let projectId = str(t.projectId) ?? NO_PROJECT_ID
    if (!projectsById[projectId]) {
      projectId = NO_PROJECT_ID
      if (!projectsById[NO_PROJECT_ID]) {
        projectsById[NO_PROJECT_ID] = {
          id: NO_PROJECT_ID,
          name: '(no project)',
          atRisk: false,
          risk: null,
          notOnRemote: null,
          daysIdle: null,
          threadIds: [],
          counts: {},
          oldAtRiskCount: 0,
        }
        projects.push(NO_PROJECT_ID)
      }
    }
    const project = projectsById[projectId]!
    const git = isObject(t.git) ? t.git : null
    const resume = isObject(t.resume) ? t.resume : null
    const lead = str(t.lead)
    const sessions = Array.isArray(t.sessions)
      ? t.sessions.filter((s): s is string => typeof s === 'string')
      : []
    const ordered = lead === null ? sessions : [lead, ...sessions.filter(s => s !== lead)]
    const state = str(t.state)
    const thread: LedgerThreadView = {
      id,
      key: str(t.key) ?? '',
      title: str(t.title) ?? id,
      projectId,
      projectName: project.name,
      effectiveState: str(t.effectiveState) ?? state ?? str(t.suggestedState) ?? 'open',
      state,
      suggestedReason: str(t.suggestedReason) ?? '',
      note: str(t.note),
      lastAt: str(t.lastAt),
      daysIdle: num(t.daysIdle),
      recency: t.recency === 'recent' ? 'recent' : 'old',
      risk: git ? str(git.risk) : null,
      notOnRemote: git ? num(git.notOnRemote) : null,
      recap: resume ? str(resume.lastRecap) : null,
      ask: resume ? str(resume.lastAsk) : null,
      lastPrompt: resume ? str(resume.lastPrompt) : null,
      sessions: ordered,
      lead,
      related: Array.isArray(t.related)
        ? t.related.flatMap(r => {
            const rid = isObject(r) ? str(r.id) : null
            return rid === null ? [] : [rid]
          })
        : [],
    }
    threads[id] = thread
    order.push(id)
    project.threadIds.push(id)
    project.counts[thread.effectiveState] = (project.counts[thread.effectiveState] ?? 0) + 1
    if (thread.effectiveState === 'at-risk' && thread.recency === 'old') project.oldAtRiskCount++
  }
  for (const thread of Object.values(threads)) {
    thread.related = thread.related.filter(rid => rid !== thread.id && threads[rid] !== undefined)
  }

  const all = order.map(id => threads[id]!)
  const atRisk = all.filter(t => t.effectiveState === 'at-risk')
  const openAll = all.filter(t => t.effectiveState === 'open' || t.effectiveState === 'active')
  const projectsAtRisk = projects.filter(id => projectsById[id]!.atRisk)

  return {
    generatedAt,
    counts: {
      projectsAtRisk: projectsAtRisk.length,
      threadsAtRisk: atRisk.length,
      open: openAll.length,
    },
    atRiskRecent: atRisk.filter(t => t.recency === 'recent').sort(byLastAtDesc).map(t => t.id),
    projectsAtRisk,
    open: [...openAll].sort(byLastAtDesc).slice(0, OPEN_LIMIT).map(t => t.id),
    projects,
    threads,
    projectsById,
  }
}

/** "just now", "12 min ago", "3 h ago", "4 d ago". */
export function formatAge(iso: string, nowMs: number): string {
  const ms = toMs(iso)
  if (ms === null) return 'at an unknown time'
  const minutes = Math.floor(Math.max(0, nowMs - ms) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.floor(hours / 24)} d ago`
}

export const formatDays = (days: number | null): string => (days === null ? '?d' : `${days}d`)

export function formatRisk(risk: string | null, notOnRemote: number | null): string {
  if (risk === null) return 'no git'
  return notOnRemote ? `${risk}, ${notOnRemote} not on remote` : risk
}

/** States in the ledger's own order, for per-project count strings. */
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

export function formatCounts(counts: Record<string, number>): string {
  const known = STATE_ORDER.filter(s => counts[s])
  const other = Object.keys(counts).filter(s => !STATE_ORDER.includes(s) && counts[s])
  const parts = [...known, ...other].map(s => `${counts[s]} ${s}`)
  return parts.length ? parts.join(', ') : 'no threads'
}

/** Cuts a text to one line of `width` cells, ending in an ellipsis when cut. */
export function clip(text: string, width: number): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  if (width <= 0) return ''
  return flat.length <= width ? flat : `${flat.slice(0, Math.max(0, width - 1))}…`
}

/**
 * Splits `budget` rows among sections that want `needs` rows: each non-empty
 * section first gets up to two, then the rest goes in order.
 */
export function allocateRows(budget: number, needs: readonly number[]): number[] {
  const out = needs.map(() => 0)
  let left = Math.max(0, Math.floor(budget))
  for (const pass of [2, Infinity]) {
    needs.forEach((need, i) => {
      const give = Math.min(need - out[i]!, pass === 2 ? 2 - out[i]! : need, left)
      if (give > 0) {
        out[i]! += give
        left -= give
      }
    })
  }
  return out
}

/**
 * Rows per list section. An expanded section takes all its items plus its
 * "Show less" row, even past `budget` (the pane body scrolls). The others
 * share what is left as `allocateRows` does, and each non-empty one keeps at
 * least one row so its "+N more" control stays reachable.
 */
export function planSections(
  budget: number,
  sections: readonly { count: number; isExpanded: boolean }[],
): number[] {
  const expandedRows = sections.reduce((sum, s) => sum + (s.isExpanded ? s.count + 1 : 0), 0)
  const shared = allocateRows(
    budget - expandedRows,
    sections.map(s => (s.isExpanded ? 0 : s.count)),
  )
  return sections.map((s, i) => {
    if (s.isExpanded) return s.count + 1
    return s.count > 0 ? Math.max(1, shared[i]!) : 0
  })
}

const cut = (text: string, width: number): string =>
  text.length <= width ? text : `${text.slice(0, Math.max(0, width - 1))}…`

/**
 * Fits a row's name and its trailing data into `width` cells: the name is cut
 * first, down to two cells; past that the data is cut too.
 */
export function splitClip(name: string, data: string, width: number): [string, string] {
  const flatName = name.replace(/\s+/g, ' ').trim()
  if (flatName.length + data.length <= width) return [flatName, data]
  if (data.length <= width - 2) return [clip(flatName, width - data.length), data]
  return [clip(flatName, 2), cut(data, Math.max(0, width - 2))]
}

/**
 * Fits `items` into `rows` rows: all of them when they fit, else the first
 * rows-1 and a "+N more" row. With no rows at all nothing is drawn.
 */
export function fitList<T>(items: readonly T[], rows: number): { shown: T[]; more: number } {
  if (items.length <= rows) return { shown: [...items], more: 0 }
  if (rows <= 0) return { shown: [], more: 0 }
  const shown = items.slice(0, rows - 1)
  return { shown, more: items.length - shown.length }
}

export type ProjectRow =
  | { kind: 'project'; projectId: string; isExpanded: boolean }
  | { kind: 'thread'; projectId: string; threadId: string }

/** The By project section as rows: each project, then its threads when expanded. */
export function projectRows(view: LedgerView, expanded: readonly string[]): ProjectRow[] {
  return view.projects.flatMap(projectId => {
    const isExpanded = expanded.includes(projectId)
    const head: ProjectRow = { kind: 'project', projectId, isExpanded }
    if (!isExpanded) return [head]
    const threads = view.projectsById[projectId]?.threadIds ?? []
    return [head, ...threads.map(threadId => ({ kind: 'thread' as const, projectId, threadId }))]
  })
}

/**
 * Replaces a leading `~` (alone, or followed by `/` or `\`) with `home`, using forward
 * slashes. Any other path, or a blank or unknown home, comes back unchanged.
 */
export function expandHome(path: string, home: string | undefined): string {
  const match = /^~(?=$|[\\/])(.*)$/s.exec(path)
  const base = (home ?? '').trim().replaceAll('\\', '/').replace(/\/+$/, '')
  if (!match || base === '') return path
  return base + (match[1] ?? '').replaceAll('\\', '/')
}

/** The last non-empty line of a stream, for a failure toast. */
export function lastLine(text: string): string {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
  return lines[lines.length - 1] ?? ''
}
