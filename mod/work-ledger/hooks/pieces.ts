// Pure functions over the curation inbox: out/pieces/inbox/<YYYY-MM-DD>/index.json
// (schemaVersion 1) and the front matter of each piece file. Both are data
// written from model output, so every field is checked before use and nothing
// from them reaches a path or a command line unvalidated.

import type { PieceView } from '../types'

export const SUPPORTED_INDEX_VERSION = 1

type Json = Record<string, unknown>
const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)

export type FrontMatterResult = { ok: true; fields: Json } | { ok: false; message: string }
export type IndexResult = { ok: true; entries: unknown[] } | { ok: false; message: string }

/** The newest `YYYY-MM-DD` folder, or null when there is none. */
export function latestInbox(entries: readonly { name: string; kind: string }[]): string | null {
  const dates = entries
    .filter(e => e.kind === 'dir' && /^\d{4}-\d{2}-\d{2}$/.test(e.name))
    .map(e => e.name)
    .sort()
  return dates[dates.length - 1] ?? null
}

/** Plain letters, digits and hyphens, never leading with a hyphen: safe as one argv item. */
export const isSafePieceId = (id: string): boolean => /^[A-Za-z0-9][A-Za-z0-9-]*$/.test(id)

/** A plain `.md` file name in the inbox folder itself. */
export const isSafePieceFile = (name: string): boolean =>
  /^[A-Za-z0-9][A-Za-z0-9._-]*\.md$/.test(name) && !name.includes('..')

/** Reads `key: <json>` lines between the first two `---` lines. */
export function parseFrontMatter(text: string): FrontMatterResult {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/)
  if (lines[0]?.trim() !== '---') return { ok: false, message: 'no front matter' }
  const end = lines.findIndex((line, i) => i > 0 && line.trim() === '---')
  if (end < 0) return { ok: false, message: 'front matter is not closed' }
  const fields: Json = {}
  for (const line of lines.slice(1, end)) {
    if (line.trim() === '') continue
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*):\s?(.*)$/)
    if (!match) return { ok: false, message: 'a line is not "key: value"' }
    const [, key = '', raw = ''] = match
    try {
      fields[key] = JSON.parse(raw)
    } catch {
      return { ok: false, message: `the value of "${key}" is not JSON` }
    }
  }
  return { ok: true, fields }
}

export function parseIndex(text: string): IndexResult {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch (err) {
    return { ok: false, message: `Malformed index.json: ${err instanceof Error ? err.message : String(err)}` }
  }
  if (!isObject(raw)) return { ok: false, message: 'index.json is not a JSON object.' }
  if (raw.schemaVersion !== SUPPORTED_INDEX_VERSION) {
    return {
      ok: false,
      message: `index.json is from an unsupported version (schemaVersion ${JSON.stringify(
        raw.schemaVersion ?? null,
      )}; this pane reads ${SUPPORTED_INDEX_VERSION}).`,
    }
  }
  if (!Array.isArray(raw.pieces)) return { ok: false, message: 'index.json has no pieces list.' }
  return { ok: true, entries: raw.pieces }
}

/**
 * Pieces from the index entries, each overlaid with its file's front matter
 * (the file is what the person edits and what `approve` copies). Entries with
 * an unsafe id or file name are left out.
 */
export function buildPieces(
  entries: readonly unknown[],
  frontMatters: Readonly<Record<string, FrontMatterResult | undefined>>,
): PieceView[] {
  const pieces: PieceView[] = []
  const seen = new Set<string>()
  for (const entry of entries) {
    if (!isObject(entry)) continue
    const id = str(entry.id)
    const file = str(entry.file)
    if (id === null || file === null || !isSafePieceId(id) || !isSafePieceFile(file) || seen.has(id)) continue
    seen.add(id)
    const fm = frontMatters[file]
    let overlay: Json = {}
    let problem: string | null = null
    if (fm === undefined) {
      problem = 'The piece file could not be read; showing the index entry.'
    } else if (!fm.ok) {
      problem = `The piece file has malformed front matter (${fm.message}); showing the index entry.`
    } else if (fm.fields.id !== undefined && fm.fields.id !== id) {
      // The front matter must name the same piece; otherwise it is ignored.
      problem = 'The piece file names another id; showing the index entry.'
    } else {
      overlay = fm.fields
    }
    const field = (name: string): unknown => (name in overlay ? overlay[name] : entry[name])
    const relevance = field('relevance')
    const audience = str(field('audience')) ?? 'unknown'
    const ids = field('sourceThreadIds')
    const indexThreads = Array.isArray(entry.sourceThreads) ? entry.sourceThreads : []
    pieces.push({
      id,
      file,
      audience,
      visibility: str(field('visibility')) ?? (audience === 'public' ? 'external' : 'internal'),
      status: str(field('status')) ?? 'proposed',
      title: str(field('title')) ?? id,
      summary: str(field('summary')),
      rationale: str(field('rationale')),
      relevance: typeof relevance === 'number' && Number.isFinite(relevance) ? relevance : null,
      sourceThreadIds: Array.isArray(ids) ? ids.filter((s): s is string => typeof s === 'string') : [],
      indexTitles: Object.fromEntries(
        indexThreads.flatMap(t => {
          const tid = isObject(t) ? str(t.id) : null
          const title = isObject(t) ? str(t.title) : null
          return tid !== null && title !== null ? [[tid, title]] : []
        }),
      ),
      problem,
    })
  }
  return pieces
}

export const proposedPieces = (pieces: readonly PieceView[]): PieceView[] =>
  pieces.filter(p => p.status === 'proposed')

/** Titles of a piece's source threads: the ledger's, else the index's, else the id. */
export function sourceTitles(piece: PieceView, ledgerTitles: Readonly<Record<string, string>>): string[] {
  return piece.sourceThreadIds.map(id => ledgerTitles[id] ?? piece.indexTitles[id] ?? id)
}

export const formatRelevance = (relevance: number | null): string =>
  relevance === null ? '?' : relevance.toFixed(2)
