"""Shared test setup: an isolated Synapse home, and lib/synapse on sys.path.

Set SYNAPSE_HOME before any Synapse module is imported, so no test can read
the real ~/.claude/synapse or re-exec into its venv.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib" / "synapse"

TMP = tempfile.mkdtemp(prefix="synapse-test-")
os.environ["SYNAPSE_HOME"] = str(Path(TMP) / "home")
for var in ("SYNAPSE_STORE", "SYNAPSE_VAULT"):
    os.environ.pop(var, None)

if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
