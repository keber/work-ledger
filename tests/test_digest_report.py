import json
import os
import tempfile
import unittest

from tests.digestfixtures import LEDGER_AT, NOW, git, ledger, previous, project, thread
from work_ledger.digest_build import build_digest
from work_ledger.digest_report import (PREVIOUS_NAME, DigestFileError, latest_record,
                                       load_previous,
                                       render_digest_markdown, write_digest)


def sample(prev=None):
    return build_digest(ledger(
        [thread("a", "at-risk", title="Fix | pipes", days=3, git=git("unpushed", 2)),
         thread("o", "at-risk", days=60, git=git("modified")),
         thread("b", "open", title="Plan", days=9, lead="s-b", recap="Did\nthings",
                ask="Ship?"),
         thread("c", "stale", title="Old", days=31)],
        [project("p-app", "app", risk="unpushed", not_on_remote=4)]), prev)


class MarkdownTest(unittest.TestCase):
    def test_sections_in_spec_order(self):
        md = render_digest_markdown(sample(previous({"c": "open"})), "2026-11-06")
        heads = ["# Weekly digest 2026-11-06", "## At risk, recent", "## No backup",
                 "## Going cold", "## Went stale this week", "## Counts"]
        positions = [md.index(h) for h in heads]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(f"Ledger generated {LEDGER_AT}", md)
        self.assertIn("previous digest 2026-10-30T09:00:00+00:00", md)

    def test_at_risk_line(self):
        md = render_digest_markdown(sample(), "2026-11-06")
        self.assertIn("- app · **Fix \\| pipes** | 3d idle | git: unpushed, 2 not on remote",
                      md)

    def test_no_backup_lines_and_total(self):
        md = render_digest_markdown(sample(), "2026-11-06")
        self.assertIn("## No backup (6 commits on no remote)", md)
        self.assertIn("- **app** main worktree: unpushed, 4 not on remote", md)
        self.assertIn("- app · **Fix \\| pipes** | 2 not on remote", md)

    def test_going_cold_block(self):
        md = render_digest_markdown(sample(), "2026-11-06")
        self.assertIn("- app · **Plan** | open, 9d idle", md)
        self.assertIn("  - Recap: Did things", md)
        self.assertIn("  - Ask: Ship?", md)
        self.assertIn("  - Resume: `claude --resume s-b`", md)

    def test_went_stale_and_first_run(self):
        md = render_digest_markdown(sample(previous({"c": "open"})), "2026-11-06")
        self.assertIn("- app · **Old**", md)
        first = render_digest_markdown(sample(), "2026-11-06")
        self.assertIn("first digest", first)
        self.assertIn("No previous digest to compare", first)

    def test_counts_section(self):
        md = render_digest_markdown(sample(previous({"a": "open", "c": "open"})), "2026-11-06")
        self.assertIn("- app: 1", md)
        self.assertIn("| at-risk | 2 | +2 |", md)
        self.assertIn("| open | 1 | -1 |", md)
        self.assertIn("| stale | 1 | +1 |", md)
        self.assertIn("| at-risk | 2 | - |", render_digest_markdown(sample(), "2026-11-06"))

    def test_empty_sections_say_none(self):
        md = render_digest_markdown(build_digest(ledger([], [])), "2026-11-06")
        self.assertEqual(md.count("- none"), 4)

    def test_resume_command_cannot_break_out_of_code_span(self):
        d = build_digest(ledger([thread("b", "open", days=9, lead="x`y")]))
        self.assertIn("`claude --resume xy`", render_digest_markdown(d, "2026-11-06"))


class LatestRecordTest(unittest.TestCase):
    def test_fields(self):
        d = sample()
        rec = latest_record(d, NOW, "C:/o/digest/2026-11-06.md")
        self.assertEqual(rec, {"schemaVersion": 1, "generatedAt": NOW.isoformat(),
                               "ledgerGeneratedAt": LEDGER_AT,
                               "path": "C:/o/digest/2026-11-06.md", "counts": d["counts"],
                               "snapshot": d["snapshot"]})


class WriteTest(unittest.TestCase):
    def test_writes_markdown_and_latest_overwriting_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "digest")
            write_digest(sample(), out, NOW, "2026-11-06")
            md_path, latest_path = write_digest(sample(previous({})), out, NOW, "2026-11-06")
            self.assertEqual(sorted(os.listdir(out)),
                             ["2026-11-06.md", "latest.json", "previous.json"])
            with open(latest_path, encoding="utf-8") as fh:
                latest = json.load(fh)
            with open(md_path, encoding="utf-8") as fh:
                md = fh.read()
        self.assertEqual(os.path.basename(md_path), "2026-11-06.md")
        self.assertEqual(latest["path"], md_path.replace("\\", "/"))
        self.assertEqual(latest["snapshot"]["a"], "at-risk")
        self.assertIn("previous digest", md)


    def test_previous_latest_is_kept_as_previous_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "digest")
            _, latest_path = write_digest(sample(), out, NOW, "2026-11-06")
            self.assertFalse(os.path.exists(os.path.join(out, PREVIOUS_NAME)))
            with open(latest_path, encoding="utf-8") as fh:
                first = fh.read()
            write_digest(sample(previous({})), out, NOW, "2026-11-13")
            with open(os.path.join(out, PREVIOUS_NAME), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), first)
        self.assertEqual(PREVIOUS_NAME, "previous.json")


class LoadPreviousTest(unittest.TestCase):
    def write(self, tmp, text):
        path = os.path.join(tmp, "latest.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_missing_file_is_no_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_previous(os.path.join(tmp, "latest.json")))

    def test_reads_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, json.dumps(previous({"a": "open"})))
            self.assertEqual(load_previous(path)["snapshot"], {"a": "open"})

    def test_invalid_json_or_schema_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            for text in ("{nope", json.dumps({"schemaVersion": 9}), "[]",
                         json.dumps({"schemaVersion": 1, "snapshot": []})):
                path = self.write(tmp, text)
                with self.assertRaises(DigestFileError):
                    load_previous(path)


if __name__ == "__main__":
    unittest.main()
