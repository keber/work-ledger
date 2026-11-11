// Synthetic ledger fixtures (schemaVersion 2). No real titles, paths or recaps.

type Row = Record<string, unknown>

export function project(id: string, over: Row = {}): Row {
  return {
    id,
    key: `repo:C:/fixture/${id}`,
    kind: 'repo',
    name: `proj-${id}`,
    path: `C:/fixture/${id}`,
    domain: 'work',
    git: { defaultBranch: 'main', branch: 'main', risk: 'safe', notOnRemote: 0 },
    threadIds: [],
    threadCount: 0,
    sessionCount: 0,
    lastAt: '2026-01-10T10:00:00.000000+00:00',
    daysIdle: 1,
    recency: 'recent',
    atRisk: false,
    ...over,
  }
}

export function thread(id: string, over: Row = {}): Row {
  return {
    id,
    key: `git:C:/fixture/p1#feature-${id}`,
    kind: 'git',
    origin: 'sessions',
    projectId: 'p1',
    title: `Thread ${id}`,
    domain: 'work',
    sessions: [],
    sessionCount: 0,
    lead: null,
    resume: null,
    firstAt: null,
    lastAt: '2026-01-10T10:00:00.123456+00:00',
    daysIdle: 1,
    recency: 'recent',
    gitScope: 'thread',
    git: { repo: 'C:/fixture/p1', branch: `feature-${id}`, risk: 'safe', notOnRemote: 0 },
    related: [],
    suggestedState: 'open',
    suggestedReason: 'no signal',
    state: null,
    note: null,
    effectiveState: 'open',
    ...over,
  }
}

export function ledgerText(projects: Row[], threads: Row[], over: Row = {}): string {
  return JSON.stringify({
    schemaVersion: 2,
    generatedAt: '2026-01-10T12:00:00.000000+00:00',
    inputs: {},
    warnings: [],
    stats: {},
    projects,
    threads,
    ...over,
  })
}

/** A day of January 2026 at noon, as the ledger writes timestamps. */
export const day = (d: number): string =>
  `2026-01-${String(d).padStart(2, '0')}T12:00:00.000000+00:00`
