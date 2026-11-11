// Synthetic curation inbox fixtures (index.json schemaVersion 1 and piece files).

type Row = Record<string, unknown>

export function pieceEntry(id: string, over: Row = {}): Row {
  const [, audience = 'team', n = '1'] = id.match(/^\d{4}-\d{2}-\d{2}-([a-z]+)-(\d+)$/) ?? []
  return {
    id,
    audience,
    visibility: audience === 'public' ? 'external' : 'internal',
    status: 'proposed',
    title: `Piece ${id}`,
    summary: `Summary of ${id}`,
    sourceThreadIds: ['r1'],
    relevance: 0.5,
    rationale: `Rationale of ${id}`,
    generatedAt: '2026-01-10T12:00:00+00:00',
    model: 'model-fixture',
    file: `${audience}-${n}.md`,
    sourceThreads: [{ id: 'r1', title: 'Index title r1', project: 'proj-p1' }],
    publishedPath: null,
    decidedAt: null,
    ...over,
  }
}

export function indexText(pieces: Row[], over: Row = {}): string {
  return JSON.stringify({
    schemaVersion: 1,
    date: '2026-01-10',
    updatedAt: '2026-01-10T12:00:00+00:00',
    pieces,
    runs: [],
    ...over,
  })
}

/** A piece file: front matter with JSON-encoded values, then the body. */
export function pieceFile(fields: Row, body = '# Title\n\nBody text.\n'): string {
  const lines = Object.entries(fields).map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
  return `---\n${lines.join('\n')}\n---\n${body}`
}

/** The front-matter fields of an index entry (the entry less its index-only keys). */
export function frontMatterOf(entry: Row): Row {
  const { file: _f, sourceThreads: _s, publishedPath: _p, decidedAt: _d, ...rest } = entry
  return rest
}
