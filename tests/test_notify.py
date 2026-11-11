import os
import subprocess
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from work_ledger import notify
from work_ledger.notify import (APP_ID, TIMEOUT_SECONDS, TOAST_TITLE, ToastError, file_uri,
                                powershell_toaster, summary_text, toast_xml)


class SummaryTest(unittest.TestCase):
    def test_three_counts(self):
        counts = {"atRiskRecent": 2, "goingCold": 5, "notOnRemoteCommits": 19}
        self.assertEqual(summary_text(counts),
                         "2 at risk (recent), 5 going cold, 19 commits on no remote")

    def test_proposal_count_is_appended_when_known(self):
        counts = {"atRiskRecent": 1, "goingCold": 0, "notOnRemoteCommits": 0}
        self.assertEqual(summary_text(counts, proposals=3),
                         "1 at risk (recent), 0 going cold, 0 commits on no remote; "
                         "3 pieces to review")
        self.assertEqual(summary_text(counts, proposals=0),
                         "1 at risk (recent), 0 going cold, 0 commits on no remote; "
                         "0 pieces to review")

    def test_missing_counts_are_zero(self):
        self.assertEqual(summary_text({}), "0 at risk (recent), 0 going cold, "
                                           "0 commits on no remote")


class ToastXmlTest(unittest.TestCase):
    def test_structure_and_protocol_activation(self):
        root = ET.fromstring(toast_xml("Title", "Body", "file:///C:/o/d.md"))
        self.assertEqual(root.tag, "toast")
        self.assertEqual(root.get("activationType"), "protocol")
        self.assertEqual(root.get("launch"), "file:///C:/o/d.md")
        texts = [t.text for t in root.iter("text")]
        self.assertEqual(texts, ["Title", "Body"])
        self.assertEqual(root.find("visual/binding").get("template"), "ToastGeneric")

    def test_text_and_attribute_are_escaped(self):
        hostile = "a<b>&\"c' </text><text>x"
        root = ET.fromstring(toast_xml(hostile, hostile, hostile))
        self.assertEqual([t.text for t in root.iter("text")], [hostile, hostile])
        self.assertEqual(root.get("launch"), hostile)

    def test_title_constant(self):
        self.assertEqual(TOAST_TITLE, "Work ledger: weekly digest")


class FileUriTest(unittest.TestCase):
    def test_absolute_file_uri(self):
        uri = file_uri(os.path.join(os.getcwd(), "out", "digest", "my file.md"))
        self.assertTrue(uri.startswith("file:///"), uri)
        self.assertTrue(uri.endswith("/out/digest/my%20file.md"), uri)


class FakeRun:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


def done(code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout="", stderr=stderr)


class PowerShellToasterTest(unittest.TestCase):
    def test_runs_static_script_on_stdin_with_values_in_environment(self):
        run = FakeRun(done())
        xml = toast_xml("T", "B; $(Remove-Item x)", "file:///C:/o/d.md")
        powershell_toaster(xml, run=run)
        args, kwargs = run.calls[0]
        self.assertTrue(args[0].lower().endswith("powershell.exe"))
        self.assertEqual(args[1:], ["-NoProfile", "-NonInteractive", "-Command", "-"])
        self.assertEqual(kwargs["input"], notify.TOAST_SCRIPT)
        self.assertNotIn("Remove-Item", kwargs["input"])
        self.assertEqual(kwargs["env"]["WORK_LEDGER_TOAST_XML"], xml)
        self.assertEqual(kwargs["env"]["WORK_LEDGER_TOAST_APP_ID"], APP_ID)
        self.assertEqual(kwargs["timeout"], TIMEOUT_SECONDS)
        self.assertEqual(TIMEOUT_SECONDS, 30)
        self.assertFalse(kwargs.get("check"))
        self.assertTrue(kwargs["capture_output"])

    def test_app_id_is_windows_powershell(self):
        self.assertEqual(APP_ID, "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
                                 "\\WindowsPowerShell\\v1.0\\powershell.exe")

    def test_script_reads_values_only_from_environment(self):
        self.assertIn("$env:WORK_LEDGER_TOAST_XML", notify.TOAST_SCRIPT)
        self.assertIn("$env:WORK_LEDGER_TOAST_APP_ID", notify.TOAST_SCRIPT)
        self.assertIn("Windows.UI.Notifications", notify.TOAST_SCRIPT)
        self.assertIn("exit 1", notify.TOAST_SCRIPT)

    def test_nonzero_exit_raises_with_stderr(self):
        with self.assertRaises(ToastError) as ctx:
            powershell_toaster("<toast/>", run=FakeRun(done(1, "boom\n")))
        self.assertIn("exit code 1", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_timeout_raises(self):
        err = subprocess.TimeoutExpired(["powershell.exe"], 30)
        with self.assertRaises(ToastError) as ctx:
            powershell_toaster("<toast/>", run=FakeRun(error=err))
        self.assertIn("timed out after 30 s", str(ctx.exception))

    def test_missing_powershell_raises(self):
        with self.assertRaises(ToastError) as ctx:
            powershell_toaster("<toast/>", run=FakeRun(error=FileNotFoundError("nope")))
        self.assertIn("cannot start PowerShell", str(ctx.exception))

    def test_executable_prefers_system_root(self):
        with mock.patch.dict(os.environ, {"SystemRoot": "C:\\Windows"}):
            self.assertEqual(notify.powershell_exe(),
                             os.path.join("C:\\Windows", "System32", "WindowsPowerShell", "v1.0",
                                          "powershell.exe"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(notify.powershell_exe(), "powershell.exe")


if __name__ == "__main__":
    unittest.main()
