import json
import os
import tempfile
import unittest

from tests.curatefixtures import LEDGER_AT, NOW, piece
from work_ledger.curate_sanitize import violations
from work_ledger.pieces_store import (INDEX_NAME, PieceError, add_run, approve, discard,
                                      inbox_dir, list_pieces, parse_piece, parse_piece_id,
                                      render_piece, slugify)

DATE = "2026-11-12"
THREADS = {"a": {"id": "a", "title": "Pipeline", "project": "app"},
           "b": {"id": "b", "title": "Docs", "project": "app"}}


def result(*kept, status="ok", rejected=()):
    return {"status": status, "warnings": [], "candidates": len(kept) + len(rejected),
            "kept": list(kept), "rejected": list(rejected)}


def run_record():
    return {"generatedAt": NOW.isoformat(), "ledgerGeneratedAt": LEDGER_AT,
            "previousDigestGeneratedAt": None, "model": "claude-opus-5-5",
            "input": {"threads": 2, "droppedByCap": 0, "chars": 100}}


def public_check(texts):
    return violations(texts, names=["work-ledger"])


class SlugTest(unittest.TestCase):
    def test_ascii_lowercase_dashes(self):
        self.assertEqual(slugify("Lecciones: pruebas ¡rápidas! en Python 3.14", "x"),
                         "lecciones-pruebas-rapidas-en-python-3-14")

    def test_traversal_and_empty_fall_back(self):
        self.assertEqual(slugify("../../etc/passwd", "x"), "etc-passwd")
        self.assertEqual(slugify("..\\..", "public-1"), "public-1")
        self.assertEqual(slugify("日本語", "public-1"), "public-1")

    def test_length_cap(self):
        slug = slugify("palabra " * 30, "x")
        self.assertLessEqual(len(slug), 60)
        self.assertFalse(slug.endswith("-"))


class PieceIdTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_piece_id("2026-11-12-public-3"), ("2026-11-12", "public", 3))

    def test_invalid(self):
        for bad in ("2026-11-12-other-1", "../2026-11-12-team-1", "2026-11-12-team-0",
                    "2026-11-12-team-1/../x", "2026-13-12-team-1", "team-1"):
            with self.assertRaises(PieceError, msg=bad):
                parse_piece_id(bad)


class FrontMatterTest(unittest.TestCase):
    def test_round_trip(self):
        meta = {"id": "x", "status": "proposed", "sourceThreadIds": ["a"], "relevance": 0.5,
                "rationale": 'con "comillas"\ny salto'}
        text = render_piece(meta, "# T\n\nCuerpo\n")
        self.assertTrue(text.startswith("---\nid: \"x\"\n"))
        self.assertEqual(parse_piece(text), (meta, "# T\n\nCuerpo\n"))

    def test_unquoted_values_edited_by_hand_are_strings(self):
        meta, body = parse_piece("---\ntitle: Mi título\nstatus: proposed\n---\nB\n")
        self.assertEqual(meta, {"title": "Mi título", "status": "proposed"})
        self.assertEqual(body, "B\n")

    def test_crlf_is_accepted(self):
        meta, body = parse_piece("---\r\nid: \"x\"\r\n---\r\nB\r\n")
        self.assertEqual(meta, {"id": "x"})

    def test_missing_front_matter(self):
        for bad in ("no front matter", "---\nid: x\n", "---\nnot a pair\n---\n"):
            with self.assertRaises(PieceError, msg=bad):
                parse_piece(bad)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.publish = os.path.join(self.tmp.name, "published")
        self.inbox = inbox_dir(self.out, DATE)

    def add(self, results):
        return add_run(self.inbox, DATE, run_record(), results, THREADS)

    def index(self):
        with open(os.path.join(self.inbox, INDEX_NAME), encoding="utf-8") as fh:
            return json.load(fh)

    def read(self, name):
        with open(os.path.join(self.inbox, name), encoding="utf-8") as fh:
            return fh.read()


class AddRunTest(StoreCase):
    def test_writes_files_with_front_matter_and_index(self):
        created = self.add({"team": result(piece("Uno", sources=("a", "b"), relevance=0.8),
                                           piece("Dos")),
                            "public": result(piece("Tres"))})
        self.assertEqual([c["id"] for c in created],
                         ["2026-11-12-team-1", "2026-11-12-team-2", "2026-11-12-public-1"])
        self.assertEqual(os.path.normcase(self.inbox),
                         os.path.normcase(os.path.join(self.out, "pieces", "inbox", DATE)))
        meta, body = parse_piece(self.read("team-1.md"))
        self.assertEqual(list(meta), ["id", "audience", "visibility", "status", "title",
                                      "summary", "sourceThreadIds", "relevance", "rationale",
                                      "generatedAt", "model"])
        self.assertEqual(meta["id"], "2026-11-12-team-1")
        self.assertEqual((meta["audience"], meta["visibility"], meta["status"]),
                         ("team", "internal", "proposed"))
        self.assertEqual(meta["sourceThreadIds"], ["a", "b"])
        self.assertEqual((meta["generatedAt"], meta["model"]),
                         (NOW.isoformat(), "claude-opus-5-5"))
        self.assertEqual(body, "# Uno\n\nCuerpo del texto.\n")
        self.assertEqual(parse_piece(self.read("public-1.md"))[0]["visibility"], "external")

        index = self.index()
        self.assertEqual(index["schemaVersion"], 1)
        self.assertEqual(index["date"], DATE)
        entry = index["pieces"][0]
        self.assertEqual(entry["file"], "team-1.md")
        self.assertEqual(entry["sourceThreads"], [{"id": "a", "title": "Pipeline",
                                                   "project": "app"},
                                                  {"id": "b", "title": "Docs",
                                                   "project": "app"}])
        for key in ("id", "audience", "visibility", "status", "title", "summary", "relevance",
                    "rationale", "sourceThreadIds", "generatedAt", "model"):
            self.assertEqual(entry[key], meta[key], key)
        self.assertIsNone(entry["publishedPath"])
        run = index["runs"][0]
        self.assertEqual(run["input"]["droppedByCap"], 0)
        self.assertEqual(run["audiences"]["team"]["kept"],
                         ["2026-11-12-team-1", "2026-11-12-team-2"])
        self.assertNotIn("Cuerpo", json.dumps(run))

    def test_failed_and_rejected_are_recorded_without_text(self):
        rejected = [{"candidate": 1, "reason": "sanitization", "rules": ["path"]}]
        self.add({"public": result(rejected=rejected),
                  "team": {"status": "failed", "warnings": ["claude: timed out"],
                           "candidates": 0, "kept": [], "rejected": []}})
        audiences = self.index()["runs"][0]["audiences"]
        self.assertEqual(audiences["public"]["rejected"], rejected)
        self.assertEqual(audiences["team"]["status"], "failed")
        self.assertEqual(audiences["team"]["warnings"], ["claude: timed out"])
        self.assertEqual(self.index()["pieces"], [])

    def test_same_day_rerun_appends_and_never_overwrites(self):
        self.add({"team": result(piece("Uno"))})
        with open(os.path.join(self.inbox, "team-1.md"), "a", encoding="utf-8") as fh:
            fh.write("edited\n")
        created = self.add({"team": result(piece("Otro"))})
        self.assertEqual(created[0]["id"], "2026-11-12-team-2")
        self.assertIn("edited", self.read("team-1.md"))
        self.assertEqual(len(self.index()["runs"]), 2)
        self.assertEqual(len(self.index()["pieces"]), 2)

    def test_corrupt_index_is_an_error(self):
        os.makedirs(self.inbox)
        with open(os.path.join(self.inbox, INDEX_NAME), "w", encoding="utf-8") as fh:
            fh.write("{")
        with self.assertRaises(PieceError):
            self.add({"team": result(piece())})

    def test_unknown_source_titles_are_null(self):
        self.add({"team": result(piece(sources=("zzz",)))})
        self.assertEqual(self.index()["pieces"][0]["sourceThreads"],
                         [{"id": "zzz", "title": None, "project": None}])


class ListTest(StoreCase):
    def test_newest_inbox_first_and_status_filter(self):
        self.add({"team": result(piece("Uno"), piece("Dos"))})
        older = inbox_dir(self.out, "2026-11-05")
        add_run(older, "2026-11-05", run_record(), {"public": result(piece("Viejo"))}, THREADS)
        os.makedirs(inbox_dir(self.out, "not-a-date"))
        discard(self.out, "2026-11-12-team-2")
        self.assertEqual([p["id"] for p in list_pieces(self.out)],
                         ["2026-11-12-team-1", "2026-11-12-team-2", "2026-11-05-public-1"])
        self.assertEqual([p["id"] for p in list_pieces(self.out, "discarded")],
                         ["2026-11-12-team-2"])

    def test_no_inbox(self):
        self.assertEqual(list_pieces(self.out), [])


class ApproveTest(StoreCase):
    def test_copies_current_text_and_sets_status(self):
        self.add({"team": result(piece("Avance: Pruebas rápidas"))})
        path = os.path.join(self.inbox, "team-1.md")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\nEditado por el usuario.\n")
        published = approve(self.out, "2026-11-12-team-1", self.publish)
        self.assertEqual(os.path.normcase(published), os.path.normcase(
            os.path.join(self.publish, "team", "2026-11-12-avance-pruebas-rapidas.md")))
        with open(published, encoding="utf-8") as fh:
            copied = fh.read()
        self.assertIn("Editado por el usuario.", copied)
        self.assertEqual(parse_piece(copied)[0]["status"], "approved")
        self.assertEqual(parse_piece(self.read("team-1.md"))[0]["status"], "approved")
        entry = self.index()["pieces"][0]
        self.assertEqual(entry["status"], "approved")
        self.assertEqual(entry["publishedPath"], published.replace("\\", "/"))
        self.assertIsNotNone(entry["decidedAt"])

    def test_existing_destination_gets_a_suffix(self):
        self.add({"team": result(piece("Mismo"), piece("Mismo"))})
        first = approve(self.out, "2026-11-12-team-1", self.publish)
        second = approve(self.out, "2026-11-12-team-2", self.publish)
        self.assertTrue(first.endswith("2026-11-12-mismo.md"))
        self.assertTrue(second.endswith("2026-11-12-mismo-2.md"))

    def test_only_proposed_pieces(self):
        self.add({"team": result(piece())})
        discard(self.out, "2026-11-12-team-1")
        with self.assertRaises(PieceError) as ctx:
            approve(self.out, "2026-11-12-team-1", self.publish)
        self.assertIn("discarded", str(ctx.exception))
        with self.assertRaises(PieceError):
            discard(self.out, "2026-11-12-team-1")

    def test_missing_piece_or_id_mismatch(self):
        with self.assertRaises(PieceError):
            approve(self.out, "2026-11-12-team-9", self.publish)
        self.add({"team": result(piece())})
        path = os.path.join(self.inbox, "team-1.md")
        text = self.read("team-1.md").replace("2026-11-12-team-1", "2026-11-12-team-7")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        with self.assertRaises(PieceError):
            approve(self.out, "2026-11-12-team-1", self.publish)

    def test_public_reruns_the_check_on_the_edited_file(self):
        self.add({"public": result(piece("Lecciones"))})
        path = os.path.join(self.inbox, "public-1.md")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("Lo hice en work-ledger, ver C:/x\n")
        with self.assertRaises(PieceError) as ctx:
            approve(self.out, "2026-11-12-public-1", self.publish, check=public_check)
        self.assertIn("project-name", str(ctx.exception))
        self.assertIn("path", str(ctx.exception))
        self.assertNotIn("C:/x", str(ctx.exception))
        self.assertFalse(os.path.exists(self.publish))
        self.assertEqual(parse_piece(self.read("public-1.md"))[0]["status"], "proposed")

    def test_public_clean_piece_is_published(self):
        self.add({"public": result(piece("Lecciones"))})
        published = approve(self.out, "2026-11-12-public-1", self.publish, check=public_check)
        self.assertTrue(os.path.isfile(published))
        self.assertIn(os.path.join(self.publish, "public"), published)

    def test_public_without_a_check_is_refused(self):
        self.add({"public": result(piece("Lecciones"))})
        with self.assertRaises(ValueError):
            approve(self.out, "2026-11-12-public-1", self.publish)


class DiscardTest(StoreCase):
    def test_sets_status_in_file_and_index(self):
        self.add({"team": result(piece())})
        discard(self.out, "2026-11-12-team-1")
        self.assertEqual(parse_piece(self.read("team-1.md"))[0]["status"], "discarded")
        self.assertEqual(self.index()["pieces"][0]["status"], "discarded")


if __name__ == "__main__":
    unittest.main()
