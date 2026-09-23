"""Run host-compiled board logic tests and PC protocol tests."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
compiler = shutil.which("gcc") or shutil.which("cc")
if compiler is None:
    raise SystemExit("gcc/cc is required for native state-machine tests")

with tempfile.TemporaryDirectory() as directory:
    executable = Path(directory) / ("test_car_logic.exe" if sys.platform == "win32" else "test_car_logic")
    subprocess.run([
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
        f"-I{ROOT / 'Core' / 'Inc'}",
        str(ROOT / "Core" / "Src" / "car_logic.c"),
        str(ROOT / "tests" / "test_car_logic.c"),
        "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)

subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
               cwd=ROOT, check=True)
