"""Static checks of the scheduling scripts. They are never executed by the tests."""

import os
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def read(name):
    with open(os.path.join(SCRIPTS, name), encoding="ascii") as fh:
        return fh.read()


class WrapperTest(unittest.TestCase):
    def test_sets_pythonpath_from_project_root_and_runs_weekly(self):
        text = read("weekly.cmd")
        self.assertIn('cd /d "%~dp0.."', text)
        self.assertIn('set "PYTHONPATH=src"', text)
        self.assertIn("-m work_ledger weekly", text)
        self.assertIn("exit /b %CODE%", text)


class InstallScriptTest(unittest.TestCase):
    def test_parameters_and_should_process(self):
        text = read("install-weekly-task.ps1")
        self.assertIn("SupportsShouldProcess = $true", text)
        for param in ("$Day", "$Time", "$Python"):
            self.assertIn(param, text)
        self.assertIn("$PSCmdlet.ShouldProcess(", text)

    def test_per_user_interactive_unelevated_task(self):
        text = read("install-weekly-task.ps1")
        self.assertIn("$TaskPath = '\\WorkLedger\\'", text)
        self.assertIn("$TaskName = 'WeeklyDigest'", text)
        self.assertIn("-StartWhenAvailable", text)
        self.assertIn("-LogonType Interactive", text)
        self.assertIn("-RunLevel Limited", text)
        self.assertIn("-Weekly", text)
        self.assertIn("-Force", text)
        self.assertNotIn("-Password", text)
        self.assertIn("weekly.cmd", text)

    def test_uninstall_removes_the_same_task(self):
        text = read("uninstall-weekly-task.ps1")
        self.assertIn("$TaskPath = '\\WorkLedger\\'", text)
        self.assertIn("$TaskName = 'WeeklyDigest'", text)
        self.assertIn("Unregister-ScheduledTask", text)
        self.assertIn("SupportsShouldProcess = $true", text)


if __name__ == "__main__":
    unittest.main()
