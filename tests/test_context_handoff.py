import os
import stat
import tempfile
import unittest
from unittest import mock

from work_ledger import context_handoff
from work_ledger.context_handoff import (HANDOFF_CAP, LEAD_CAP, MAX_FILES, excerpt_note,
                                         find_handoff)


def write(root, rel, text="notes\n", mtime=None):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class FindHandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def names(self, notes):
        return [os.path.relpath(n["path"], self.root).replace("\\", "/") for n in notes]

    def test_missing_or_none_path(self):
        self.assertEqual(find_handoff(None), [])
        self.assertEqual(find_handoff(os.path.join(self.root, "nope")), [])

    def test_patterns_case_insensitive_in_root_and_doc_dirs(self):
        write(self.root, "handoff.md", mtime=1_700_000_100)
        write(self.root, "qa/Agent-Next-Steps-2.MD", mtime=1_700_000_300)
        write(self.root, "docs/ESTADO_PROYECTO.md", mtime=1_700_000_200)
        notes = find_handoff(self.root, max_files=5)
        self.assertEqual(self.names(notes),
                         ["qa/Agent-Next-Steps-2.MD", "docs/ESTADO_PROYECTO.md", "handoff.md"])

    def test_other_files_and_deeper_dirs_ignored(self):
        write(self.root, "README.md")
        write(self.root, "status.txt")
        write(self.root, "docs/deep/STATUS.md")
        write(self.root, "src/NEXT-STEPS.md")
        write(self.root, ".claude/STATUS.md")
        self.assertEqual(self.names(find_handoff(self.root)), [".claude/STATUS.md"])

    def test_most_recent_first_and_capped_count(self):
        for i in range(5):
            write(self.root, f"NEXT-STEPS-{i}.md", mtime=1_700_000_000 + i)
        notes = find_handoff(self.root)
        self.assertEqual(len(notes), MAX_FILES)
        self.assertEqual(self.names(notes)[0], "NEXT-STEPS-4.md")

    def test_fields_and_text_cap(self):
        write(self.root, "HANDOFF.md", "a" * (HANDOFF_CAP + 500), mtime=1_700_000_000)
        write(self.root, "STATUS.md", "short", mtime=1_699_000_000)
        notes = find_handoff(self.root)
        big, small = notes
        self.assertLessEqual(len(big["text"]), LEAD_CAP)
        self.assertTrue(big["truncated"])
        self.assertEqual(big["bytes"], HANDOFF_CAP + 500)
        self.assertEqual(big["modifiedAt"], "2023-11-14T22:13:20+00:00")
        self.assertTrue(big["path"].endswith("/HANDOFF.md"))
        self.assertNotIn("\\", big["path"])
        self.assertEqual(small["text"], "short")
        self.assertFalse(small["truncated"])

    def test_directories_named_like_handoff_are_ignored(self):
        os.makedirs(os.path.join(self.root, "HANDOFF.md"))
        self.assertEqual(find_handoff(self.root), [])


def long_note():
    return "\n".join([
        "# Agent next steps",
        "",
        "> Read first: work on branch qa/export, run the suite before pushing.",
        "",
        "## Resumen (2026-07-31)",
        "OLD SUMMARY " * 220,
        "",
        "## Backlog",
        "UNDATED BACKLOG " * 70,
        "",
        "### 2026-10-02",
        "october work " * 45,
        "",
        "### 2026-11-04",
        "NEWEST STATUS " * 45,
        "",
        "## Review notes 2026-11-01",
        "november review " * 40,
        "",
        "```",
        "# 2026-12-31 not a heading inside a code fence",
        "```",
    ])


class ExcerptNoteTest(unittest.TestCase):
    def test_short_note_kept_whole_with_its_toc(self):
        text, toc = excerpt_note("# T\n\nshort\n## Next\nx")
        self.assertEqual(text, "# T\n\nshort\n## Next\nx")
        self.assertEqual(toc, [{"line": 1, "level": 1, "heading": "T"},
                               {"line": 4, "level": 2, "heading": "Next"}])

    def test_long_note_keeps_title_and_lead_only(self):
        note = long_note()
        self.assertGreater(len(note), HANDOFF_CAP)
        text, _ = excerpt_note(note)
        self.assertTrue(text.startswith("# Agent next steps"))
        self.assertIn("Read first: work on branch qa/export", text)
        self.assertNotIn("OLD SUMMARY", text)
        self.assertNotIn("NEWEST STATUS", text)
        self.assertLessEqual(len(text), LEAD_CAP)

    def test_toc_lists_every_heading_with_line_numbers(self):
        _, toc = excerpt_note(long_note())
        headings = [(t["line"], t["level"], t["heading"]) for t in toc]
        self.assertEqual([h[2] for h in headings],
                         ["Agent next steps", "Resumen (2026-07-31)", "Backlog", "2026-10-02",
                          "2026-11-04", "Review notes 2026-11-01"])
        self.assertEqual(headings[0][:2], (1, 1))
        self.assertEqual(headings[1][:2], (5, 2))
        lines = long_note().splitlines()
        for line, level, heading in headings:
            self.assertEqual(lines[line - 1], "#" * level + " " + heading)

    def test_read_first_section_after_title_is_part_of_the_lead(self):
        note = "\n".join(["# Title", "## Novedades", "see section 4", "## 1. Old",
                          "x " * 2000, "## 4. Pending for the next iteration", "recent"])
        text, _ = excerpt_note(note)
        self.assertEqual(text, "# Title\n## Novedades\nsee section 4")

    def test_lead_is_bounded(self):
        note = "# Title\n" + "> intro " * 400 + "\n## Next\n" + "y" * 4000
        text, _ = excerpt_note(note)
        self.assertLessEqual(len(text), LEAD_CAP)
        self.assertTrue(text.endswith("..."))

    def test_note_without_headings(self):
        text, toc = excerpt_note("z" * 5000)
        self.assertEqual(toc, [])
        self.assertLessEqual(len(text), LEAD_CAP)

    def test_find_handoff_long_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "AGENT-NEXT-STEPS.md", long_note())
            note, = find_handoff(tmp)
        self.assertTrue(note["truncated"])
        self.assertTrue(note["path"].endswith("/AGENT-NEXT-STEPS.md"))
        self.assertEqual(note["lines"], len(long_note().splitlines()))
        self.assertEqual(len(note["toc"]), 6)
        self.assertNotIn("sections", note)

    def test_find_handoff_short_note_is_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "STATUS.md", "# S\nall good")
            note, = find_handoff(tmp)
        self.assertFalse(note["truncated"])
        self.assertEqual(note["text"], "# S\nall good")


class FakeEntry:
    def __init__(self, path, kind="file", junction=False, reparse=False):
        self.path, self.name = path, os.path.basename(path)
        self.kind, self.junction, self.reparse = kind, junction, reparse

    def is_dir(self, follow_symlinks=True):
        return self.kind == "dir"

    def is_file(self, follow_symlinks=True):
        return self.kind == "file"

    def is_junction(self):
        return self.junction

    def is_symlink(self):
        return False

    def stat(self, follow_symlinks=True):
        attrs = stat.FILE_ATTRIBUTE_REPARSE_POINT if self.reparse else 0
        return os.stat_result((0o100644, 0, 0, 1, 0, 0, 10, 1_700_000_000, 1_700_000_000,
                               1_700_000_000)) if not attrs else _ReparseStat()


class _ReparseStat:
    st_mtime = 1_700_000_000
    st_size = 10
    st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT


class JunctionTest(unittest.TestCase):
    def test_junction_dirs_and_reparse_files_are_skipped(self):
        root = "C:/fake/project"
        listing = {
            root: [FakeEntry(root + "/docs", "dir", junction=True),
                   FakeEntry(root + "/qa", "dir"),
                   FakeEntry(root + "/HANDOFF.md", "file", junction=True)],
            root + "/qa": [FakeEntry(root + "/qa/STATUS.md", "file", reparse=True),
                           FakeEntry(root + "/qa/NEXT-STEPS.md", "file")],
        }
        scanned, opened = [], []

        def fake_scandir(path):
            scanned.append(path)
            return iter(listing.get(path, []))

        def fake_read(path, limit):
            opened.append(path)
            return "notes"

        with mock.patch.object(context_handoff.os, "scandir", side_effect=fake_scandir), \
                mock.patch.object(context_handoff.os.path, "isdir", return_value=True), \
                mock.patch.object(context_handoff, "_read_text", side_effect=fake_read):
            notes = find_handoff(root)
        self.assertNotIn(root + "/docs", scanned)
        self.assertIn(root + "/qa", scanned)
        self.assertEqual(opened, [root + "/qa/NEXT-STEPS.md"])
        self.assertEqual(len(notes), 1)


if __name__ == "__main__":
    unittest.main()
