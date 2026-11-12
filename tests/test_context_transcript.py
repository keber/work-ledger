import os
import tempfile
import unittest

from tests.sessionfixtures import assistant_text, lines, meta, msg, tool, tool_result, user, write_jsonl
from work_ledger.context_transcript import (ENTRY_MAX, OUTSIDE_SOURCE, clip, entry_key,
                                           excerpt_lines, is_transcript_path, read_excerpt)


def wrap_up(recap, ask=None, **kw):
    return tool("mcp__ccd_turn__wrap_up", {"recap": recap, "ask": ask}, **kw)


def texts(excerpt):
    return [(e["role"], e["text"]) for e in excerpt["entries"]]


class ClipTest(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(clip("  a\n\n  b\tc  "), "a b c")

    def test_truncates_with_ellipsis_marker(self):
        text = clip("x" * 500, 300)
        self.assertEqual(len(text), 300)
        self.assertTrue(text.endswith("..."))

    def test_short_text_unchanged(self):
        self.assertEqual(clip("hola"), "hola")


class ExcerptLinesTest(unittest.TestCase):
    def test_user_prompts_and_final_assistant_text_per_turn(self):
        excerpt = excerpt_lines(lines(
            user("fix the login bug", ts="2026-11-01T10:00:00Z"),
            assistant_text("Looking at it", ts="2026-11-01T10:00:05Z"),
            tool("Bash", {"command": "pytest"}, ts="2026-11-01T10:00:06Z"),
            tool_result(ts="2026-11-01T10:00:07Z"),
            assistant_text("Fixed: the token expired early.", ts="2026-11-01T10:01:00Z"),
            user("dale", ts="2026-11-01T10:02:00Z"),
            assistant_text("Done.", ts="2026-11-01T10:03:00Z"),
        ))
        self.assertEqual(texts(excerpt), [
            ("user", "fix the login bug"),
            ("assistant", "Fixed: the token expired early."),
            ("user", "dale"),
            ("assistant", "Done."),
        ])
        self.assertEqual(excerpt["entries"][1]["at"], "2026-11-01T10:01:00Z")
        self.assertEqual(excerpt["omitted"], 0)
        self.assertIsNone(excerpt["gapAfter"])

    def test_no_tool_output_or_tool_input(self):
        excerpt = excerpt_lines(lines(
            user("go"), tool("Bash", {"command": "cat secrets.txt"}), tool_result(),
            assistant_text("ok")))
        joined = " ".join(e["text"] for e in excerpt["entries"])
        self.assertNotIn("secret", joined)
        self.assertNotIn("cat ", joined)

    def test_wrap_up_recap_replaces_intermediate_text(self):
        excerpt = excerpt_lines(lines(
            user("ship it"),
            assistant_text("Running the tests now"),
            wrap_up("Tests pass; not pushed.", ask="Push?"),
            assistant_text("All green. Push?"),
        ))
        self.assertEqual(texts(excerpt), [
            ("user", "ship it"),
            ("recap", "Tests pass; not pushed. | ask: Push?"),
            ("assistant", "All green. Push?"),
        ])

    def test_recap_without_ask(self):
        excerpt = excerpt_lines(lines(user("x"), wrap_up("Done and merged.")))
        self.assertEqual(texts(excerpt)[-1], ("recap", "Done and merged."))

    def test_skips_meta_sidechain_compact_and_injected_tags(self):
        excerpt = excerpt_lines(lines(
            user("<system-reminder>internal</system-reminder>"),
            user("<command-name>/clear</command-name>"),
            user("hidden meta", isMeta=True),
            user("subagent prompt", isSidechain=True),
            assistant_text("subagent answer", isSidechain=True),
            user("This session is being continued...", isCompactSummary=True),
            user("real prompt"),
            meta("last-prompt", lastPrompt="real prompt"),
            "not json",
            assistant_text("real answer"),
        ))
        self.assertEqual(texts(excerpt), [("user", "real prompt"), ("assistant", "real answer")])

    def test_user_content_list_text_items(self):
        record = msg("user", [{"type": "text", "text": "first"}, {"type": "image"},
                              {"type": "text", "text": "second"}])
        self.assertEqual(texts(excerpt_lines(lines(record))), [("user", "first second")])

    def test_entries_are_truncated(self):
        excerpt = excerpt_lines(lines(user("y" * 1000)))
        self.assertEqual(len(excerpt["entries"][0]["text"]), ENTRY_MAX)

    def test_keeps_head_and_tail_and_counts_omitted(self):
        records = []
        for i in range(10):
            records.append(user(f"prompt {i}"))
        excerpt = excerpt_lines(lines(*records), head=2, tail=3)
        self.assertEqual([t for _, t in texts(excerpt)],
                         ["prompt 0", "prompt 1", "prompt 7", "prompt 8", "prompt 9"])
        self.assertEqual(excerpt["omitted"], 5)
        self.assertEqual(excerpt["gapAfter"], 2)
        self.assertEqual(excerpt["total"], 10)

    def test_empty_transcript(self):
        excerpt = excerpt_lines([])
        self.assertEqual(excerpt["entries"], [])
        self.assertEqual(excerpt["total"], 0)


class ReadExcerptTest(unittest.TestCase):
    def test_reads_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(os.path.join(tmp, "p", "s.jsonl"), user("hola"),
                               assistant_text("qué tal"))
            excerpt = read_excerpt(path)
        self.assertIsNone(excerpt["error"])
        self.assertEqual(texts(excerpt), [("user", "hola"), ("assistant", "qué tal")])

    def test_missing_file_is_an_error_not_an_exception(self):
        excerpt = read_excerpt(os.path.join(tempfile.gettempdir(), "nope", "missing.jsonl"))
        self.assertEqual(excerpt["entries"], [])
        self.assertIn("transcript unreadable: FileNotFoundError", excerpt["error"])

    def test_returns_keys_of_every_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(os.path.join(tmp, "p", "s.jsonl"),
                               *[user(f"p{i}", ts=f"2026-11-01T10:0{i}:00Z") for i in range(6)])
            excerpt = read_excerpt(path, head=1, tail=1)
        self.assertEqual(len(excerpt["keys"]), 6)
        self.assertIn(entry_key({"at": "2026-11-01T10:03:00Z", "role": "user", "text": "p3"}),
                      excerpt["keys"])


class SharedEntriesTest(unittest.TestCase):
    def test_entries_seen_in_another_session_are_skipped_and_counted(self):
        shared = [user("parent prompt", ts="2026-11-01T10:00:00Z"),
                  assistant_text("parent answer", ts="2026-11-01T10:01:00Z")]
        parent = excerpt_lines(lines(*shared))
        seen = {k: "s-parent" for k in parent["keys"]}
        fork = excerpt_lines(lines(*shared, user("fork prompt", ts="2026-11-02T10:00:00Z")),
                             seen=seen)
        self.assertEqual(texts(fork), [("user", "fork prompt")])
        self.assertEqual(fork["sharedWith"], {"s-parent": 2})
        self.assertEqual(fork["total"], 1)

    def test_shared_entries_do_not_use_head_slots(self):
        shared = [user(f"old {i}", ts=f"2026-11-01T10:0{i}:00Z") for i in range(5)]
        seen = {k: "a" for k in excerpt_lines(lines(*shared))["keys"]}
        fork = excerpt_lines(lines(*shared, user("new", ts="2026-11-02T10:00:00Z")), head=2,
                             tail=0, seen=seen)
        self.assertEqual(texts(fork), [("user", "new")])


class TranscriptPathTest(unittest.TestCase):
    def test_inside_source_and_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(os.path.join(tmp, "proj", "s.jsonl"), user("x"))
            self.assertTrue(is_transcript_path(path, tmp))
            self.assertTrue(is_transcript_path(path.replace("\\", "/"), tmp + "/"))

    def test_outside_source(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            path = write_jsonl(os.path.join(other, "s.jsonl"), user("x"))
            self.assertFalse(is_transcript_path(path, tmp))
            dotted = os.path.join(tmp, "proj", "..", "..", os.path.basename(other), "s.jsonl")
            self.assertFalse(is_transcript_path(dotted, tmp))

    def test_not_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "proj", "notes.txt")
            os.makedirs(os.path.dirname(path))
            open(path, "w").close()
            self.assertFalse(is_transcript_path(path, tmp))

    def test_missing_values(self):
        self.assertFalse(is_transcript_path(None, "C:/x"))
        self.assertFalse(is_transcript_path("C:/x/a.jsonl", None))

    def test_read_excerpt_refuses_paths_outside_the_source(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            path = write_jsonl(os.path.join(other, "s.jsonl"), user("secret"))
            excerpt = read_excerpt(path, source_root=tmp)
        self.assertEqual(excerpt["entries"], [])
        self.assertEqual(excerpt["error"], OUTSIDE_SOURCE)
        self.assertIn("path outside sessions source", OUTSIDE_SOURCE)


if __name__ == "__main__":
    unittest.main()
