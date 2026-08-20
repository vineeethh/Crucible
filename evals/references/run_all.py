"""Run every seed-case reference calculator and print one JSON line per case.

Usage:  python run_all.py [optional dataset path]
Exit code is nonzero if any reference fails, so this can gate CI later.
"""

import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
scripts = sorted(here.glob("case_*.py"))
args = sys.argv[1:]

failed = []
for script in scripts:
    proc = subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, cwd=here
    )
    if proc.returncode != 0:
        failed.append(script.name)
        print(f"FAIL {script.name}\n{proc.stderr}", file=sys.stderr)
    else:
        print(proc.stdout, end="")

if failed:
    sys.exit(f"{len(failed)} reference(s) failed: {failed}")
