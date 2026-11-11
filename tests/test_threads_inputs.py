import json
import os
import tempfile
import unittest

from tests.threadfixtures import inventory, overrides, sessions_report
from work_ledger.threads_inputs import InputError, check_schema, load_inputs


class CheckSchemaTest(unittest.TestCase):
    def test_accepted_versions(self):
        check_schema(inventory(), "inventory", (2,))
        check_schema(sessions_report(version=2), "sessions", (2, 3))
        check_schema(sessions_report(version=3), "sessions", (2, 3))

    def test_unknown_version_names_input_and_versions(self):
        with self.assertRaises(InputError) as ctx:
            check_schema(sessions_report(version=4), "sessions", (2, 3))
        message = str(ctx.exception)
        self.assertIn("sessions", message)
        self.assertIn("schemaVersion 4", message)
        self.assertIn("2, 3", message)

    def test_not_an_object(self):
        with self.assertRaises(InputError):
            check_schema([], "inventory", (2,))


class LoadInputsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def test_loads_all_three(self):
        inv = self.write("i.json", inventory())
        ses = self.write("s.json", sessions_report())
        ovr = self.write("o.json", overrides())
        loaded = load_inputs(inv, ses, ovr)
        self.assertEqual(loaded[0]["schemaVersion"], 2)
        self.assertEqual(loaded[1]["schemaVersion"], 3)
        self.assertEqual(loaded[2]["schemaVersion"], 1)

    def test_absent_overrides_is_none(self):
        inv = self.write("i.json", inventory())
        ses = self.write("s.json", sessions_report())
        self.assertIsNone(load_inputs(inv, ses, os.path.join(self.dir, "none.json"))[2])
        self.assertIsNone(load_inputs(inv, ses, None)[2])

    def test_missing_or_invalid_input_is_clear_error(self):
        ses = self.write("s.json", sessions_report())
        with self.assertRaises(InputError) as ctx:
            load_inputs(os.path.join(self.dir, "missing.json"), ses, None)
        self.assertIn("inventory", str(ctx.exception))
        bad = self.write("bad.json", "{nope")
        with self.assertRaises(InputError) as ctx:
            load_inputs(bad, ses, None)
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_unknown_inventory_version(self):
        inv = self.write("i.json", dict(inventory(), schemaVersion=1))
        ses = self.write("s.json", sessions_report())
        with self.assertRaises(InputError) as ctx:
            load_inputs(inv, ses, None)
        self.assertIn("schemaVersion 1", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
