import json
import unittest

from tests.curatefixtures import output, piece
from work_ledger.curate_build import (AUDIENCES, load_prompt, run_audience, select_candidates)
from work_ledger.curate_claude import ClaudeError, ClaudeReply
from work_ledger.curate_sanitize import violations


def public_check(texts):
    return violations(texts, names=["work-ledger"])


class AudiencesTest(unittest.TestCase):
    def test_table(self):
        self.assertEqual({a: (v["visibility"], v["max"]) for a, v in AUDIENCES.items()},
                         {"portfolio": ("internal", 2), "team": ("internal", 2),
                          "public": ("external", 1)})


class SelectCandidatesTest(unittest.TestCase):
    def test_top_by_relevance_up_to_the_maximum(self):
        pieces = [piece("A", relevance=0.2), piece("B", relevance=0.9), piece("C", relevance=0.5)]
        kept, rejected = select_candidates(pieces, {"a"}, 2)
        self.assertEqual([p["title"] for p in kept], ["B", "C"])
        self.assertEqual(rejected, [{"candidate": 1, "reason": "over-limit", "rules": []}])

    def test_ties_keep_model_order(self):
        kept, _ = select_candidates([piece("A"), piece("B")], {"a"}, 1)
        self.assertEqual(kept[0]["title"], "A")

    def test_unknown_source_threads_are_discarded(self):
        pieces = [piece("A", sources=("a", "zzz"), relevance=0.9), piece("B", sources=("a",))]
        kept, rejected = select_candidates(pieces, {"a"}, 2)
        self.assertEqual([p["title"] for p in kept], ["B"])
        self.assertEqual(rejected, [{"candidate": 1, "reason": "unknown-source-thread",
                                     "rules": []}])

    def test_sanitization_rejects_with_rules_only(self):
        pieces = [piece("En work-ledger", body="ver C:/x", relevance=0.9),
                  piece("Lecciones", relevance=0.1)]
        kept, rejected = select_candidates(pieces, {"a"}, 1, check=public_check)
        self.assertEqual([p["title"] for p in kept], ["Lecciones"])
        self.assertEqual(rejected, [{"candidate": 1, "reason": "sanitization",
                                     "rules": ["project-name", "path"]}])
        self.assertNotIn("work-ledger", json.dumps(rejected))

    def test_sanitization_covers_title_summary_body_and_rationale(self):
        for field in ("title", "summary", "body", "rationale"):
            bad = dict(piece(), **{field: "work-ledger"})
            kept, _ = select_candidates([bad], {"a"}, 1, check=public_check)
            self.assertEqual(kept, [], field)


class FakePort:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, system_prompt, schema, input_text):
        self.calls.append((system_prompt, schema, input_text))
        if self.error:
            raise self.error
        return self.reply


DATA = {"audience": "team", "threads": [{"id": "a"}, {"id": "b"}]}


class RunAudienceTest(unittest.TestCase):
    def test_ok(self):
        port = FakePort(ClaudeReply(output(piece(relevance=0.4), piece(relevance=0.8),
                                           piece(relevance=0.1)), ["note"]))
        result = run_audience("team", DATA, port, "PROMPT")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["candidates"], 3)
        self.assertEqual([p["relevance"] for p in result["kept"]], [0.8, 0.4])
        self.assertEqual(result["warnings"], ["note"])
        prompt, schema, text = port.calls[0]
        self.assertEqual(prompt, "PROMPT")
        self.assertEqual(json.loads(schema)["type"], "object")
        self.assertEqual(json.loads(text), DATA)

    def test_port_failure_skips_the_audience(self):
        result = run_audience("team", DATA, FakePort(error=ClaudeError("timed out")), "P")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["kept"], [])
        self.assertIn("timed out", result["warnings"][0])

    def test_schema_mismatch_skips_the_audience(self):
        port = FakePort(ClaudeReply({"pieces": [{"title": "x"}]}, []))
        result = run_audience("team", DATA, port, "P")
        self.assertEqual(result["status"], "failed")
        self.assertIn("schema mismatch", result["warnings"][0])

    def test_public_runs_the_check(self):
        port = FakePort(ClaudeReply(output(piece("work-ledger")), []))
        result = run_audience("public", DATA, port, "P", check=public_check)
        self.assertEqual(result["kept"], [])
        self.assertEqual(result["rejected"][0]["reason"], "sanitization")

    def test_public_without_a_check_is_refused(self):
        with self.assertRaises(ValueError):
            run_audience("public", DATA, FakePort(), "P")


class PromptsTest(unittest.TestCase):
    def test_every_audience_has_an_english_prompt_asking_for_spanish(self):
        for audience in AUDIENCES:
            text = load_prompt(audience)
            self.assertIn("Spanish", text, audience)
            self.assertIn("neutral", text.lower(), audience)
            self.assertIn("invent", text.lower(), audience)
            self.assertIn("sourceThreadIds", text, audience)

    def test_public_prompt_asks_for_lessons_not_systems(self):
        text = load_prompt("public").lower()
        self.assertIn("lessons", text)
        self.assertIn("clients", text)

    def test_unknown_audience(self):
        with self.assertRaises(ValueError):
            load_prompt("../secrets")


if __name__ == "__main__":
    unittest.main()
