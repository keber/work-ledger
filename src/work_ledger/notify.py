"""Windows toast for the weekly digest.

The toast is shown through a port: any callable taking the toast XML and raising
ToastError on failure. `powershell_toaster` is the real adapter; tests inject fakes.
"""

import os
import pathlib
import subprocess
from xml.sax.saxutils import escape, quoteattr

TOAST_TITLE = "Work ledger: weekly digest"
# AppUserModelID registered by Windows PowerShell; lets an unpackaged script raise toasts.
APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
TIMEOUT_SECONDS = 30
XML_ENV = "WORK_LEDGER_TOAST_XML"
APP_ID_ENV = "WORK_LEDGER_TOAST_APP_ID"

# Static script fed on stdin. Every dynamic value comes from the environment, never from
# the script text. One statement per line: `-Command -` runs stdin line by line.
TOAST_SCRIPT = (
    "$ErrorActionPreference = 'Stop'\n"
    "try { "
    "$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
    "ContentType = WindowsRuntime]; "
    "$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
    "ContentType = WindowsRuntime]; "
    "$doc = New-Object Windows.Data.Xml.Dom.XmlDocument; "
    f"$doc.LoadXml($env:{XML_ENV}); "
    "$toast = New-Object Windows.UI.Notifications.ToastNotification $doc; "
    f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:{APP_ID_ENV})"
    ".Show($toast); "
    "exit 0 "
    "} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }\n"
)


class ToastError(Exception):
    """The toast could not be shown."""


def summary_text(counts, proposals=None):
    """Digest counts; `proposals` (pieces to review) is appended when known."""
    text = (f"{counts.get('atRiskRecent') or 0} at risk (recent), "
            f"{counts.get('goingCold') or 0} going cold, "
            f"{counts.get('notOnRemoteCommits') or 0} commits on no remote")
    if proposals is not None:
        text += f"; {proposals} pieces to review"
    return text


def file_uri(path):
    """`file:///` URI of a local path, percent-encoded."""
    return pathlib.Path(os.path.abspath(path)).as_uri()


def toast_xml(title, body, launch_uri):
    """ToastGeneric XML; clicking it opens launch_uri through protocol activation."""
    return (f'<toast activationType="protocol" launch={quoteattr(launch_uri)}>'
            '<visual><binding template="ToastGeneric">'
            f"<text>{escape(title)}</text><text>{escape(body)}</text>"
            "</binding></visual></toast>")


def powershell_exe():
    """Full path of Windows PowerShell, so a powershell.exe earlier on PATH is not used."""
    root = os.environ.get("SystemRoot")
    if not root:
        return "powershell.exe"
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def powershell_toaster(xml, run=subprocess.run):
    """Show the toast with Windows PowerShell and WinRT. Raises ToastError."""
    env = dict(os.environ)
    env[XML_ENV] = xml
    env[APP_ID_ENV] = APP_ID
    args = [powershell_exe(), "-NoProfile", "-NonInteractive", "-Command", "-"]
    try:
        result = run(args, input=TOAST_SCRIPT, env=env, capture_output=True, text=True,
                     timeout=TIMEOUT_SECONDS, check=False,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise ToastError(f"PowerShell timed out after {TIMEOUT_SECONDS} s") from None
    except OSError as exc:
        raise ToastError(f"cannot start PowerShell: {exc}") from None
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:500] or "no error output"
        raise ToastError(f"PowerShell exit code {result.returncode}: {detail}")
