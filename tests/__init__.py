import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Tests never read the user's gitignored work-ledger.local.toml: the config path points at
# an empty file. Tests that need a config pass --config or patch this variable.
os.environ["WORK_LEDGER_CONFIG"] = os.devnull
