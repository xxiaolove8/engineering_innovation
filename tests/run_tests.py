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
        str(ROOT / "Core" / "Src" / "car_pid.c"),
        str(ROOT / "tests" / "test_car_logic.c"),
        "-lm",
        "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)

    store_executable = Path(directory) / ("test_car_pid_store.exe" if sys.platform == "win32" else "test_car_pid_store")
    subprocess.run([
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
        f"-I{ROOT / 'tests' / 'fake_hal'}",
        f"-I{ROOT / 'Core' / 'Inc'}",
        str(ROOT / "Core" / "Src" / "car_pid.c"),
        str(ROOT / "Core" / "Src" / "car_pid_store.c"),
        str(ROOT / "tests" / "test_car_pid_store.c"),
        "-lm", "-o", str(store_executable),
    ], check=True)
    subprocess.run([str(store_executable)], check=True)

    hw_executable = Path(directory) / ("test_car_hw.exe" if sys.platform == "win32" else "test_car_hw")
    subprocess.run([
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
        f"-I{ROOT / 'tests' / 'fake_hw'}", f"-I{ROOT / 'Core' / 'Inc'}",
        *[str(ROOT / "Core" / "Src" / name) for name in
          ("car_hw.c", "car_app.c", "car_logic.c", "car_pid.c")],
        str(ROOT / "tests" / "test_car_hw.c"), "-lm", "-o", str(hw_executable),
    ], check=True)
    subprocess.run([str(hw_executable)], check=True)

    system_executable = Path(directory) / ("test_system_init.exe" if sys.platform == "win32" else "test_system_init")
    subprocess.run([
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-DSTM32F407xx",
        f"-I{ROOT / 'tests' / 'fake_system'}",
        str(ROOT / "Core" / "Src" / "system_stm32f4xx.c"),
        str(ROOT / "tests" / "test_system_init.c"), "-o", str(system_executable),
    ], check=True)
    subprocess.run([str(system_executable)], check=True)

    for hooks in (False, True):
        syscall_executable = Path(directory) / (f"test_syscalls_{hooks}.exe" if sys.platform == "win32" else f"test_syscalls_{hooks}")
        subprocess.run([
            compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror",
            f"-I{ROOT / 'Core' / 'Inc'}", f"-I{ROOT / 'tests' / 'fake_posix'}",
            *(["-DTEST_IO_HOOKS"] if hooks else []),
            str(ROOT / "tests" / "test_syscalls.c"),
            "-o", str(syscall_executable),
        ], check=True)
        subprocess.run([str(syscall_executable)], check=True)

    sysmem_executable = Path(directory) / ("test_sysmem.exe" if sys.platform == "win32" else "test_sysmem")
    subprocess.run([
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
        str(ROOT / "tests" / "test_sysmem.c"), "-o", str(sysmem_executable),
    ], check=True)
    subprocess.run([str(sysmem_executable)], check=True)

subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
               cwd=ROOT, check=True)
