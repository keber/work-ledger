import unittest

from tests.curatefixtures import curate_ledger, thread
from tests.digestfixtures import git, project
from tests.threadfixtures import inventory, repo, wt
from work_ledger.curate_sanitize import (DEFAULT_COMPANY_TERMS, RULES, internal_names,
                                         parse_denylist, violations)


COMPANY = ("acme", "acmefruit")


def check(text, names=(), company=COMPANY, denylist=()):
    return violations([text], names=names, company=company, denylist=denylist)


class CleanTextTest(unittest.TestCase):
    def test_lessons_text_passes(self):
        text = ("# Lo que aprendí\n\nSeparar la lógica pura de los puertos facilita las "
                "pruebas. Usé TCP/IP, input/output y Python 3.14 sin dependencias.")
        self.assertEqual(check(text, names=["work-ledger"]), [])

    def test_rule_names(self):
        self.assertEqual(RULES, ("project-name", "company", "email", "url", "path",
                                 "ip-address", "ticket-id", "denylist"))

    def test_defaults(self):
        self.assertEqual(DEFAULT_COMPANY_TERMS, ())

    def test_no_company_terms_by_default(self):
        self.assertEqual(violations(["Acme Corp"]), [])


class ProjectNameTest(unittest.TestCase):
    def test_case_insensitive_and_separator_tolerant(self):
        for text in ("Avance en WORK-LEDGER", "el work ledger", "work_ledger listo",
                     "workledger"):
            self.assertEqual(check(text, names=["work-ledger"]), ["project-name"], text)

    def test_whole_words_only(self):
        self.assertEqual(check("una aplicación", names=["app"]), [])
        self.assertEqual(check("la app nueva", names=["app"]), ["project-name"])

    def test_accents_are_folded(self):
        self.assertEqual(check("Exportación lista", names=["exportacion"]), ["project-name"])

    def test_short_names_are_ignored(self):
        self.assertEqual(check("a de la qa", names=["a", "qa"]), [])


class CompanyTest(unittest.TestCase):
    def test_name_domain_and_accents(self):
        for text in ("Trabajo en Acmé", "ver acmefruit.com", "AcmeFruitSA"):
            self.assertEqual(check(text), ["company"], text)

    def test_configurable(self):
        self.assertEqual(check("Globex Corp", company=["globex"]), ["company"])
        self.assertEqual(check("acme", company=[]), [])


class PatternRulesTest(unittest.TestCase):
    def assert_rule(self, rule, *texts):
        for text in texts:
            self.assertIn(rule, check(text), text)

    def test_email(self):
        self.assert_rule("email", "escribe a ana.perez+x@example.org")

    def test_url(self):
        self.assert_rule("url", "ver https://example.org/x", "en www.example.org",
                         "file:///C:/x")

    def test_paths(self):
        self.assert_rule("path", r"en C:\Users\x\repo", "en C:/Users/x", "en /home/user/repo",
                         "en ~/.claude/projects", r"en src\work_ledger", r"\\server\share")

    def test_ip_addresses(self):
        self.assert_rule("ip-address", "host 10.0.0.12", "fe80:0:0:0:200:f8ff:fe21:67cf")

    def test_ticket_ids(self):
        self.assert_rule("ticket-id", "cierra #123", "ver AB#123", "PBI 123", "pbi #45",
                         "Bug 991", "tarea 12", "ABC-123")

    def test_markdown_heading_is_not_a_ticket(self):
        self.assertEqual(check("# Título\n\n## Sección 2"), [])


class DenylistTest(unittest.TestCase):
    def test_parse_skips_blank_lines_and_comments(self):
        self.assertEqual(parse_denylist("Cliente X\n\n# comment\n  otro  \n"),
                         ["Cliente X", "otro"])

    def test_matches_case_insensitive_substring(self):
        self.assertEqual(check("el ClienteXYZ", denylist=["clientex"]), ["denylist"])


class ViolationsTest(unittest.TestCase):
    def test_reports_every_rule_once_in_rule_order(self):
        text = "acme en C:/x y a@b.co, acme de nuevo"
        self.assertEqual(check(text), ["company", "email", "path"])

    def test_checks_every_text(self):
        self.assertEqual(violations(["limpio", "ver #12"]), ["ticket-id"])


class InternalNamesTest(unittest.TestCase):
    def test_from_ledger_and_inventory(self):
        led = curate_ledger(
            [thread("a", git=git(repo="C:/r/app", worktree="C:/r/app-wt-feat"))],
            [project("p-app", "app"), project("p-dir", "notes", risk=None, path="C:/w/notes")])
        inv = inventory(repo("C:/r/svc", [wt("C:/r/svc", is_main=True),
                                          wt("C:/r/.worktrees/svc-fix")]))
        self.assertEqual(internal_names(led, inv),
                         ["app", "app-wt-feat", "notes", "svc", "svc-fix"])

    def test_tolerates_missing_parts(self):
        self.assertEqual(internal_names({"projects": None, "threads": [{"git": None}]}, None),
                         [])


if __name__ == "__main__":
    unittest.main()
