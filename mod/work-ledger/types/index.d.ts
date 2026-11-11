// View model of out/ledger.json (schemaVersion 2) and the pane's state atoms.

export type LedgerThreadView = {
  id: string
  key: string
  title: string
  projectId: string
  projectName: string
  effectiveState: string
  /** Override state, null when the state is the suggested one. */
  state: string | null
  suggestedReason: string
  note: string | null
  lastAt: string | null
  daysIdle: number | null
  recency: 'recent' | 'old'
  risk: string | null
  notOnRemote: number | null
  recap: string | null
  ask: string | null
  lastPrompt: string | null
  /** Session ids, the lead first. */
  sessions: string[]
  lead: string | null
  /** Ids of related threads (fork family) that exist in the ledger. */
  related: string[]
}

export type LedgerProjectView = {
  id: string
  name: string
  atRisk: boolean
  risk: string | null
  notOnRemote: number | null
  daysIdle: number | null
  /** Thread ids in ledger order. */
  threadIds: string[]
  /** Thread count per effective state. */
  counts: Record<string, number>
  /** At-risk threads older than 30 days, counted rather than listed. */
  oldAtRiskCount: number
}

export type LedgerView = {
  generatedAt: string
  counts: {
    projectsAtRisk: number
    threadsAtRisk: number
    open: number
    /** Open or active threads idle 14 days or more. */
    goingCold: number
    /** Commits on no remote, feature branches and main worktrees together. */
    unbacked: number
  }
  /** Thread ids: effective state at-risk and recency recent, newest first. */
  atRiskRecent: string[]
  /** Project ids with atRisk, in ledger order. */
  projectsAtRisk: string[]
  /** Thread ids: effective state open or active, newest first, at most 15. */
  open: string[]
  /** Project ids in ledger order. */
  projects: string[]
  threads: Record<string, LedgerThreadView>
  projectsById: Record<string, LedgerProjectView>
}

export type LedgerErrorKind = 'missing' | 'malformed' | 'unsupported' | 'invalid'

export type LedgerError = { kind: LedgerErrorKind; message: string }

export type LedgerLoad =
  | { status: 'unloaded' }
  | { status: 'error'; error: LedgerError }
  | { status: 'ok'; view: LedgerView }

export type LedgerSection = 'pieces' | 'risk' | 'projects' | 'open' | 'all'

/** A curation piece of the latest inbox: its index entry overlaid with its front matter. */
export type PieceView = {
  id: string
  file: string
  audience: string
  visibility: string
  status: string
  title: string
  summary: string | null
  rationale: string | null
  relevance: number | null
  sourceThreadIds: string[]
  /** Source thread titles the index recorded, by thread id. */
  indexTitles: Record<string, string>
  /** Why the file's front matter was not used, when it was not. */
  problem: string | null
}

export type PiecesLoad =
  | { status: 'none' }
  | { status: 'error'; date: string; message: string }
  | { status: 'ok'; date: string; pieces: PieceView[] }

export type PieceActionKind = 'approve' | 'discard'

export type PieceAction = { id: string | null; action: PieceActionKind | null; startedAt: number }

export type LedgerRefresh = { isRunning: boolean; startedAt: number }

declare module 'claude-code' {
  interface PluginState {
    'work-ledger': {
      ledger: Shaped<LedgerLoad>
      selected: Shaped<string | null>
      expanded: Shaped<string[]>
      /** List sections showing all their items: pieces, risk, projects, open, all. */
      showAll: Shaped<LedgerSection[]>
      refresh: Shaped<LedgerRefresh>
      pieces: Shaped<PiecesLoad>
      selectedPiece: Shaped<string | null>
      pieceAction: Shaped<PieceAction>
    }
  }
}
