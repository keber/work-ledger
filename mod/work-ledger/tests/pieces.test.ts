import { describe, expect, test } from 'claude-code/testing'

import {
  buildPieces,
  isSafePieceId,
  isSafePieceFile,
  latestInbox,
  parseFrontMatter,
  parseIndex,
  proposedPieces,
  sourceTitles,
} from '../hooks/pieces'
import { frontMatterOf, indexText, pieceEntry, pieceFile } from './pieces-fixtures'

const dir = (name: string) => ({ name, kind: 'dir' as const })
const file = (name: string) => ({ name, kind: 'file' as const })

describe('latestInbox', () => {
  test('takes the newest YYYY-MM-DD folder and ignores everything else', () => {
    expect(
      latestInbox([dir('2026-01-03'), dir('2026-01-10'), dir('notes'), file('2026-02-01'), dir('2026-1-20')]),
    ).toBe('2026-01-10')
    expect(latestInbox([file('x'), dir('drafts')])).toBe(null)
    expect(latestInbox([])).toBe(null)
  })
})

describe('parseFrontMatter', () => {
  test('reads JSON-encoded values between the --- fences', () => {
    const parsed = parseFrontMatter(
      pieceFile({ id: 'a', relevance: 0.75, sourceThreadIds: ['t1', 't2'], title: 'Uno: dos "tres"' }),
    )
    expect(parsed).toEqual({
      ok: true,
      fields: { id: 'a', relevance: 0.75, sourceThreadIds: ['t1', 't2'], title: 'Uno: dos "tres"' },
    })
  })

  test('accepts CRLF line endings and a byte-order mark', () => {
    const parsed = parseFrontMatter('﻿---\r\nid: "a"\r\nstatus: "proposed"\r\n---\r\n# a\r\n')
    expect(parsed).toEqual({ ok: true, fields: { id: 'a', status: 'proposed' } })
  })

  test('refuses text with no front matter, an unclosed one, or a bad value', () => {
    expect(parseFrontMatter('# no front matter').ok).toBe(false)
    expect(parseFrontMatter('---\nid: "a"\n').ok).toBe(false)
    const bad = parseFrontMatter('---\nid: "a"\nrelevance: not-json\n---\n')
    expect(bad.ok).toBe(false)
    if (!bad.ok) expect(bad.message).toMatch(/relevance/)
    const noKey = parseFrontMatter('---\njust text\n---\n')
    expect(noKey.ok).toBe(false)
  })
})

describe('parseIndex', () => {
  test('reads the pieces of a schemaVersion 1 index', () => {
    const parsed = parseIndex(indexText([pieceEntry('2026-01-10-team-1')]))
    expect(parsed.ok).toBe(true)
    if (parsed.ok) expect(parsed.entries).toHaveLength(1)
  })

  test('malformed JSON, another schemaVersion or no pieces list is an error', () => {
    const malformed = parseIndex('{"pieces": [')
    expect(malformed.ok ? '' : malformed.message).toMatch(/^Malformed index.json: /)
    const version = parseIndex(indexText([], { schemaVersion: 2 }))
    expect(version.ok ? '' : version.message).toMatch(/unsupported version/)
    const noList = parseIndex(JSON.stringify({ schemaVersion: 1 }))
    expect(noList.ok ? '' : noList.message).toMatch(/no pieces list/)
  })
})

describe('buildPieces', () => {
  test('the front matter wins over the index, which it may have been edited past', () => {
    const entry = pieceEntry('2026-01-10-team-1', { title: 'Index title' })
    const fm = parseFrontMatter(pieceFile({ ...frontMatterOf(entry), title: 'Edited title', status: 'discarded' }))
    const [piece] = buildPieces([entry], { 'team-1.md': fm })
    expect(piece).toMatchObject({ title: 'Edited title', status: 'discarded', problem: null })
  })

  test('a missing or malformed piece file falls back to the index and says so', () => {
    const a = pieceEntry('2026-01-10-team-1')
    const b = pieceEntry('2026-01-10-team-2')
    const pieces = buildPieces([a, b], { 'team-2.md': { ok: false, message: 'bad value' } })
    expect(pieces.map(p => [p.title, p.problem])).toEqual([
      ['Piece 2026-01-10-team-1', 'The piece file could not be read; showing the index entry.'],
      ['Piece 2026-01-10-team-2', 'The piece file has malformed front matter (bad value); showing the index entry.'],
    ])
  })

  test('entries with an unsafe id or file name are left out', () => {
    const pieces = buildPieces(
      [
        pieceEntry('2026-01-10-team-1'),
        pieceEntry('--publish-dir', { file: 'team-2.md' }),
        pieceEntry('2026-01-10-team-3', { file: '../../elsewhere.md' }),
        { title: 'no id' },
      ],
      {},
    )
    expect(pieces.map(p => p.id)).toEqual(['2026-01-10-team-1'])
  })

  test('proposedPieces keeps only proposed ones; relevance and source ids are typed', () => {
    const pieces = buildPieces(
      [
        pieceEntry('2026-01-10-team-1', { relevance: 0.9 }),
        pieceEntry('2026-01-10-team-2', { status: 'approved' }),
        pieceEntry('2026-01-10-public-1', { relevance: 'high', sourceThreadIds: ['x', 3] }),
      ],
      {},
    )
    const proposed = proposedPieces(pieces)
    expect(proposed.map(p => p.id)).toEqual(['2026-01-10-team-1', '2026-01-10-public-1'])
    expect(proposed[1]).toMatchObject({ relevance: null, sourceThreadIds: ['x'], visibility: 'external' })
  })
})

describe('helpers', () => {
  test('a piece id is safe only as plain letters, digits and hyphens, not leading with one', () => {
    expect(isSafePieceId('2026-01-10-public-1')).toBe(true)
    expect(isSafePieceId('--evil')).toBe(false)
    expect(isSafePieceId('a b')).toBe(false)
    expect(isSafePieceId('')).toBe(false)
  })

  test('a piece file is a plain .md name in the same folder', () => {
    expect(isSafePieceFile('team-1.md')).toBe(true)
    expect(isSafePieceFile('../team-1.md')).toBe(false)
    expect(isSafePieceFile('sub/team-1.md')).toBe(false)
    expect(isSafePieceFile('team-1.txt')).toBe(false)
  })

  test('source titles come from the ledger, then the index, then the id', () => {
    const [piece] = buildPieces(
      [
        pieceEntry('2026-01-10-team-1', {
          sourceThreadIds: ['t1', 't2', 't3'],
          sourceThreads: [{ id: 't2', title: 'From the index', project: 'p' }],
        }),
      ],
      {},
    )
    expect(sourceTitles(piece!, { t1: 'From the ledger' })).toEqual(['From the ledger', 'From the index', 't3'])
  })
})
