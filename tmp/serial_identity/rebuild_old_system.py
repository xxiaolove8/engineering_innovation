from pathlib import Path
import hashlib
import json
import shlex
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "Debug"
OUTPUT = Path(__file__).resolve().parent
OUTPUT.mkdir(parents=True, exist_ok=True)
source = OUTPUT / "system_stm32f4xx_before_vtor.c"
source.write_bytes(subprocess.check_output(["git", "show", "HEAD:Core/Src/system_stm32f4xx.c"], cwd=ROOT))
entries = json.loads((BUILD / "compile_commands.json").read_text())
entry = next(item for item in entries if item["file"].endswith("system_stm32f4xx.c"))
compile_args = entry["command"].split()
gcc = Path(compile_args[0])
old_object = OUTPUT / "system_stm32f4xx_before_vtor.c.obj"
compile_args[compile_args.index("-o") + 1] = str(old_object)
compile_args[compile_args.index("-c") + 1] = str(source)
subprocess.run(compile_args, cwd=OUTPUT, check=True)

lines = (BUILD / "build.ninja").read_text().splitlines()
link_index = next(i for i, line in enumerate(lines) if line.startswith("build if_car.elf "))
object_names = lines[link_index].split(": C_EXECUTABLE_LINKER__if_car_Debug ", 1)[1].split(" || ", 1)[0].split()
variables = {}
for line in lines[link_index + 1:]:
    if not line.startswith("  "):
        break
    key, value = line.strip().split(" = ", 1)
    variables[key] = value
objects = [str(old_object if name.endswith("/system_stm32f4xx.c.obj") else BUILD / name) for name in object_names]
flags = shlex.split(variables["FLAGS"])
link_flags = shlex.split(variables["LINK_FLAGS"])
link_flags = [f"-Wl,-Map={OUTPUT / 'if_car_debug_before_vtor.map'}" if flag.startswith("-Wl,-Map=") else flag for flag in link_flags]
elf = OUTPUT / "if_car_debug_before_vtor.elf"
binary = OUTPUT / "if_car_debug_before_vtor.bin"
subprocess.run([str(gcc), *flags, *link_flags, *objects, "-o", str(elf), *shlex.split(variables["LINK_LIBRARIES"])], cwd=OUTPUT, check=True)
subprocess.run([str(gcc.with_name("arm-none-eabi-objcopy.exe")), "-O", "binary", str(elf), str(binary)], cwd=OUTPUT, check=True)
candidate = binary.read_bytes()
result = {"candidate": str(binary), "size": len(candidate), "sha256": hashlib.sha256(candidate).hexdigest(),
          "vectors": [hex(word) for word in struct.unpack_from("<8I", candidate)], "comparisons": []}
for name in ("mcu_serial_before_vtor_20261001.bin", "mcu_app_before_serial_20261001.bin"):
    backup = ROOT / "tmp" / name
    if not backup.exists():
        continue
    actual = backup.read_bytes()
    compared = min(len(candidate), len(actual))
    offsets = [i for i in range(compared) if candidate[i] != actual[i]]
    result["comparisons"].append({"backup": str(backup), "backup_size": len(actual), "compared_bytes": compared,
                                  "matching_bytes": compared - len(offsets), "first_difference": offsets[0] if offsets else None,
                                  "exact_candidate_match": len(actual) >= len(candidate) and not offsets,
                                  "candidate_region_sha256": hashlib.sha256(actual[:len(candidate)]).hexdigest()})
(OUTPUT / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
