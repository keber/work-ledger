import os
import tempfile
import unittest
from unittest import mock

from work_ledger import config
from work_ledger.config import (CONFIG_ENV, CONFIG_NAME, Config, ConfigError, company_terms,
                                config_path, load_config, parse_config, roots, setting)

HOME = lambda p: p.replace("~", "H:", 1) if p.startswith("~") else p  # noqa: E731


class ParseConfigTest(unittest.TestCase):
    def test_empty_text_is_all_defaults(self):
        self.assertEqual(parse_config(""), Config())

    def test_reads_every_key(self):
        text = ('[curation]\ncompany_terms = ["acme", "acmefruit"]\n'
                'publish_dir = "D:/pub"\nclaude = "D:/bin/claude.exe"\n'
                '[inventory]\nroots = ["D:/a", "D:/b"]\n')
        self.assertEqual(parse_config(text),
                         Config(company_terms=("acme", "acmefruit"), publish_dir="D:/pub",
                                claude="D:/bin/claude.exe", roots=("D:/a", "D:/b")))

    def test_paths_expand_the_home_dir(self):
        text = ('[curation]\npublish_dir = "~/pub"\nclaude = "~/bin/claude.exe"\n'
                '[inventory]\nroots = ["~/Proyectos"]\n')
        with mock.patch("os.path.expanduser", side_effect=HOME):
            cfg = parse_config(text)
        self.assertEqual((cfg.publish_dir, cfg.claude, cfg.roots),
                         ("H:/pub", "H:/bin/claude.exe", ("H:/Proyectos",)))

    def test_empty_company_list_is_kept(self):
        self.assertEqual(parse_config("[curation]\ncompany_terms = []\n").company_terms, ())

    def test_invalid_toml(self):
        with self.assertRaisesRegex(ConfigError, "invalid TOML"):
            parse_config("[curation\n", "x.toml")

    def test_wrong_types(self):
        for text in ('[curation]\ncompany_terms = "acme"\n',
                     '[curation]\ncompany_terms = ["acme", 3]\n',
                     '[curation]\npublish_dir = 5\n',
                     '[inventory]\nroots = "D:/a"\n',
                     'curation = 1\n'):
            with self.assertRaises(ConfigError, msg=text):
                parse_config(text)

    def test_unknown_keys_are_rejected(self):
        with self.assertRaisesRegex(ConfigError, "company_term"):
            parse_config('[curation]\ncompany_term = ["acme"]\n')
        with self.assertRaisesRegex(ConfigError, "extra"):
            parse_config('[extra]\nx = 1\n')


class ConfigPathTest(unittest.TestCase):
    def test_cli_wins_over_environment(self):
        self.assertEqual(config_path("~/a.toml", {CONFIG_ENV: "D:/b.toml"}, "D:/root",
                                     expand=HOME), ("H:/a.toml", True))

    def test_environment_wins_over_project_file(self):
        self.assertEqual(config_path(None, {CONFIG_ENV: "~/b.toml"}, "D:/root", expand=HOME),
                         ("H:/b.toml", True))

    def test_default_is_the_local_file_at_the_project_root(self):
        self.assertEqual(config_path(None, {}, "D:/root"),
                         (os.path.join("D:/root", CONFIG_NAME), False))
        self.assertEqual(CONFIG_NAME, "work-ledger.local.toml")


class LoadConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, text=None):
        path = os.path.join(self.tmp.name, "c.toml")
        if text is not None:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return path

    def test_reads_the_file(self):
        cfg = load_config(self.path('[curation]\ncompany_terms = ["acme"]\n'), explicit=False)
        self.assertEqual(cfg.company_terms, ("acme",))

    def test_missing_default_file_is_all_defaults(self):
        self.assertEqual(load_config(self.path(), explicit=False), Config())

    def test_missing_explicit_file_is_an_error(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_config(self.path(), explicit=True)

    def test_unreadable_file_is_an_error(self):
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_config(self.tmp.name, explicit=False)


class PrecedenceTest(unittest.TestCase):
    CFG = Config(company_terms=("fromfile",), publish_dir="D:/file", claude="D:/file.exe",
                 roots=("D:/file",))

    def test_company_terms_cli_env_file_default(self):
        env = {"WORK_LEDGER_COMPANY_TERMS": "envco, envco.com"}
        self.assertEqual(company_terms(["cli"], env, self.CFG), ("cli",))
        self.assertEqual(company_terms(None, env, self.CFG), ("envco", "envco.com"))
        self.assertEqual(company_terms(None, {}, self.CFG), ("fromfile",))
        self.assertEqual(company_terms(None, {}, Config()), ())

    def test_blank_company_terms_are_dropped(self):
        self.assertEqual(company_terms(["", " x "], {}, Config()), ("x",))
        self.assertEqual(company_terms(None, {"WORK_LEDGER_COMPANY_TERMS": " , "}, self.CFG),
                         ("fromfile",))

    def test_roots_cli_env_file_default(self):
        env = {"WORK_LEDGER_ROOTS": os.pathsep.join(["~/e1", "D:/e2"])}
        with mock.patch("os.path.expanduser", side_effect=HOME):
            self.assertEqual(roots(["D:/cli"], env, self.CFG, ["D:/def"]), ["D:/cli"])
            self.assertEqual(roots(None, env, self.CFG, ["D:/def"]), ["H:/e1", "D:/e2"])
        self.assertEqual(roots(None, {}, self.CFG, ["D:/def"]), ["D:/file"])
        self.assertEqual(roots(None, {}, Config(), ["D:/def"]), ["D:/def"])

    def test_path_settings(self):
        env = {"WORK_LEDGER_PUBLISH_DIR": "~/env"}
        with mock.patch("os.path.expanduser", side_effect=HOME):
            self.assertEqual(setting("~/cli", env, "WORK_LEDGER_PUBLISH_DIR", "D:/file"),
                             "H:/cli")
            self.assertEqual(setting(None, env, "WORK_LEDGER_PUBLISH_DIR", "D:/file"), "H:/env")
        self.assertEqual(setting(None, {}, "WORK_LEDGER_PUBLISH_DIR", "D:/file"), "D:/file")
        self.assertIsNone(setting(None, {"WORK_LEDGER_PUBLISH_DIR": ""},
                                  "WORK_LEDGER_PUBLISH_DIR", None))

    def test_environment_names(self):
        self.assertEqual((config.CONFIG_ENV, config.COMPANY_ENV, config.ROOTS_ENV,
                          config.CLAUDE_ENV, config.PUBLISH_ENV),
                         ("WORK_LEDGER_CONFIG", "WORK_LEDGER_COMPANY_TERMS", "WORK_LEDGER_ROOTS",
                          "WORK_LEDGER_CLAUDE", "WORK_LEDGER_PUBLISH_DIR"))


class ExampleFileTest(unittest.TestCase):
    def test_tracked_example_parses_with_neutral_values(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = load_config(os.path.join(root, "work-ledger.example.toml"), explicit=True)
        self.assertEqual(cfg.company_terms, ("acme", "acmefruit"))
        self.assertTrue(cfg.roots)


if __name__ == "__main__":
    unittest.main()
