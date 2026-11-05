"""Run the frozen BIGWORK source using the existing environment's interpreter."""
from pathlib import Path
import sys

source = Path(__file__).resolve().parent / "source/src"
package = source / "classical_casimir"
if not (package / "__init__.py").is_file():
    raise RuntimeError("stage the application source with setup.sh first")
sys.path.insert(0, str(source))
import classical_casimir
if Path(classical_casimir.__file__).resolve() != (package / "__init__.py").resolve():
    raise RuntimeError("unexpected classical_casimir package location")
from classical_casimir.cli import main
sys.exit(main())
