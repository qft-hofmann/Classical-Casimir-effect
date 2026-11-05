"""Run the existing small BEM regression tests within a time and memory budget."""
from pathlib import Path
import sys
from classical_casimir.budget import run_budgeted

root = Path(__file__).resolve().parents[1]
result = run_budgeted([sys.executable,"-m","pytest",str(root/"tests/test_bem.py"),"-q"],
                      root/"output/smoke/tests.log",seconds=600,memory_gib=8)
print(result)
raise SystemExit(0 if result["returncode"] == 0 else 1)
