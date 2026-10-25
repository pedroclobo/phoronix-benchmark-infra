#!/usr/bin/env python3
"""Compiler wrapper used while PTS builds a test.

`bench.py` puts symlinks to this file first on PATH, named `cc`, `gcc`,
`clang`, `c++`, `g++`, `clang++`, `nasm` and `yasm`. Build scripts that
honor `$CC` and build scripts that hardcode `gcc` both end up here. The name
we were called as decides what to run:

- C/C++ names run the variant's clang or clang++ with rewritten flags. We
  measure wall time and peak memory, and record what was produced.
- Assembler names run the real tool from PATH. We only record its outputs, so
  the post-install audit knows those objects are expected.

Everything is configured by `BENCH_*` environment variables set by `bench.py`.
This file only uses the standard library and must stay fast to start, because
it runs once per compiler invocation.
"""

import fcntl
import hashlib
import json
import os
import re
import resource
import shlex
import subprocess
import sys
import time
from pathlib import Path

CXX_NAMES = {"clang++", "g++", "c++"}
CC_NAMES = {"clang", "gcc", "cc"}
ASM_NAMES = {"nasm", "yasm"}

# Invocations that only probe the compiler (autoconf checks, version
# queries). They run unmodified and are not recorded, as before.
PROBE_ARGS = {
    "-V",
    "-v",
    "--version",
    "-qversion",
    "-dumpmachine",
    "-dumpversion",
    "-print-search-dirs",
    "-print-multi-os-directory",
}
PROBE_PREFIXES = ("-print-prog-name=", "-print-file-name=")

SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".c++", ".C", ".m", ".mm"}
ASM_SUFFIXES = {".s", ".S", ".asm"}

# Options whose value is the next argument. We need this to tell an option
# value (`-o foo.c`, `-MF x.d`) apart from an input file.
TAKES_VALUE = {
    "-o", "-MF", "-MT", "-MQ", "-MJ", "-I", "-D", "-U", "-include",
    "-imacros", "-isystem", "-iquote", "-idirafter", "-iprefix",
    "-iwithprefix", "-x", "-Xclang", "-Xlinker", "-Xassembler",
    "-Xpreprocessor", "-mllvm", "-L", "-l", "-arch", "-target", "-isysroot",
    "-F", "-framework", "-install_name", "-current_version",
    "-compatibility_version", "-u", "-e", "-T", "-z", "-rpath", "--param",
    "-dependency-file", "-sectcreate",
}

OPT_RE = re.compile(r"-O([0-3sz]|fast|g)?")


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        sys.exit(f"wrapper.py: {name} is not set; run through bench.py")
    return value


def locked_append(path: Path, text: str) -> None:
    """Append under an exclusive lock. `make -j` runs many wrappers at once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(text)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def file_hash(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()


def split_inputs(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """Return (input files, {option: value}) for the options we care about."""
    inputs, values = [], {}
    i = 0
    while i < len(args):
        a = args[i]
        if a in TAKES_VALUE and i + 1 < len(args):
            values[a] = args[i + 1]
            i += 2
            continue
        if not a.startswith("-") or a == "-":
            inputs.append(a)
        i += 1
    return inputs, values


def is_source(path: str) -> bool:
    return Path(path).suffix in SOURCE_SUFFIXES


def predicted_outputs(args: list[str], cwd: Path) -> list[Path]:
    """Files this command writes, following the driver's naming rules."""
    inputs, values = split_inputs(args)
    if "-o" in values:
        return [cwd / values["-o"]]
    if "-E" in args:
        return []  # preprocessed output goes to stdout
    suffix = ".s" if "-S" in args else ".o" if "-c" in args else None
    if suffix is None:
        return [cwd / "a.out"]
    return [cwd / (Path(s).stem + suffix) for s in inputs
            if is_source(s) or Path(s).suffix in ASM_SUFFIXES]


def rewrite(args: list[str], opt: str, flags: list[str],
            drop: set[str]) -> list[str]:
    """Drop blacklisted flags, force the opt level and append variant flags.

    Every `-O<level>` becomes `opt`. If a compile has no `-O` at all (its
    build file ignores CFLAGS), `opt` is appended, so no file silently builds
    at -O0.
    """
    out, saw_opt = [], False
    for a in args:
        if a in drop:
            continue
        if OPT_RE.fullmatch(a):
            out.append(opt)
            saw_opt = True
            continue
        out.append(a)
    out += flags
    inputs, _ = split_inputs(args)
    if not saw_opt and any(is_source(s) for s in inputs):
        out.append(opt)
    return out


def record_outputs(paths: list[Path]) -> list[dict]:
    recs = []
    for p in paths:
        if p.is_file():
            recs.append({"path": str(p.resolve()), "hash": file_hash(p)})
    return recs


def run_assembler(name: str, args: list[str]) -> int:
    """Run the real nasm/yasm and record its outputs for the audit."""
    shim_dir = os.path.realpath(env("BENCH_SHIM_DIR"))
    path = [d for d in os.environ.get("PATH", "").split(os.pathsep)
            if os.path.realpath(d) != shim_dir]
    real = None
    for d in path:
        cand = Path(d) / name
        if cand.is_file() and os.access(cand, os.X_OK):
            real = cand
            break
    if real is None:
        sys.exit(f"wrapper.py: {name} not found on PATH")
    rc = subprocess.run([str(real), *args]).returncode
    cwd = Path.cwd()
    outs = []
    if "-o" in args:
        outs = [cwd / args[args.index("-o") + 1]]
    record = {
        "kind": "assembler",
        "round": int(env("BENCH_ROUND", "1")),
        "invoked_as": name,
        "cwd": str(cwd),
        "args": args,
        "rc": rc,
        "outputs": record_outputs(outs),
    }
    locked_append(Path(env("BENCH_DATA_DIR")) / "compile.jsonl",
                  json.dumps(record) + "\n")
    return rc


# --- main -------------------------------------------------------------------


def main() -> int:
    invoked_as = Path(sys.argv[0]).name
    raw = sys.argv[1:]

    if invoked_as in ASM_NAMES:
        return run_assembler(invoked_as, raw)

    driver = "clang++" if invoked_as in CXX_NAMES else "clang"
    clang = Path(env("BENCH_LLVM_PATH")) / driver

    if any(a in PROBE_ARGS or a.startswith(PROBE_PREFIXES)
           or Path(a).stem == "conftest" for a in raw):
        os.execv(clang, [str(clang), *raw])

    opt = env("BENCH_OPT")
    flags = shlex.split(env("BENCH_FLAGS", ""))
    drop = set(env("BENCH_DROP_FLAGS", "").split("\n")) - {""}
    args = rewrite(raw, opt, flags, drop)
    rnd = int(env("BENCH_ROUND", "1"))
    data = Path(env("BENCH_DATA_DIR"))
    cwd = Path.cwd()

    # Time and peak memory of the clang child only, not of this script.
    # ru_maxrss is in KiB on Linux and in bytes on macOS.
    start = time.perf_counter_ns()
    proc = subprocess.run([str(clang), *args], stderr=subprocess.PIPE)
    elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    rss_kb = rss // 1024 if sys.platform == "darwin" else rss
    sys.stderr.buffer.write(proc.stderr)
    sys.stderr.flush()

    inputs, _ = split_inputs(args)
    sources = [s for s in inputs if is_source(s)]
    # Inline remarks need a second compile, so the first one stays a clean
    # time measurement. Remarks don't change between rounds: only round 1.
    if (env("BENCH_INLINE_REMARKS", "0") == "1" and rnd == 1
            and proc.returncode == 0 and sources):
        r = subprocess.run([str(clang), *args, "-Rpass=inline"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        remarks = [l for l in r.stderr.decode(errors="replace").splitlines()
                   if "remark:" in l]
        if remarks:
            locked_append(data / "inline-remarks.txt", "\n".join(remarks) + "\n")

    record = {
        "kind": "cc",
        "round": rnd,
        "invoked_as": invoked_as,
        "driver": driver,
        "cwd": str(cwd),
        "args": args,
        "sources": sources,
        "ms": elapsed_ms,
        "rss_kb": rss_kb,
        "rc": proc.returncode,
        "outputs": (record_outputs(predicted_outputs(args, cwd))
                    if proc.returncode == 0 else []),
    }
    locked_append(data / "compile.jsonl", json.dumps(record) + "\n")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
