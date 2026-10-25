#!/usr/bin/env python3
"""Compiler wrapper used while PTS builds a test.

`bench.py` puts small shims first on PATH, named `cc`, `gcc`, `clang`,
`c++`, `g++`, `clang++`, `nasm` and `yasm`. Each runs this file with
bench.py's own Python and passes its name in BENCH_INVOKED_AS. Build scripts
that honor `$CC` and build scripts that hardcode `gcc` both end up here. The
name we were called as decides what to run:

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

# Output and dependency-file options. Crash capture strips these to build a
# command that writes IR somewhere else.
OUTPUT_FLAGS_WITH_VALUE = {"-o", "-MF", "-MT", "-MQ", "-MJ"}
OUTPUT_FLAGS = {"-c", "-S", "-E", "-MD", "-MMD", "-MP", "-M", "-MM"}

OPT_RE = re.compile(r"-O([0-3sz]|fast|g)?")

# Text that only shows up in stderr when LLVM itself crashes, as opposed to an
# ordinary compile error in the test's sources.
CRASH_RE = re.compile(
    rb"PLEASE submit a bug report|Assertion .* failed|Assertion failed:|"
    rb"LLVM ERROR:|"
    rb"frontend command failed due to signal"
)


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


# --- crash capture ----------------------------------------------------------


def signature(stderr: str) -> str:
    """A short, stable string that identifies this crash in stderr.

    `interesting.sh` greps for it, so llvm-reduce keeps only inputs that hit
    the *same* crash, not any crash. glibc prints assertions as
    ``Assertion `cond' failed``, macOS as `Assertion failed: (cond), function
    f, file x, line n.`; the file and line are left out so the signature
    survives a rebuild.
    """
    m = re.search(r"Assertion `.*' failed", stderr)
    if m:
        return m.group(0)
    m = re.search(r"Assertion failed: \(.*\), function [^,]+", stderr)
    if m:
        return m.group(0)
    m = re.search(r"LLVM ERROR: .*", stderr)
    if m:
        return m.group(0).strip()
    return "PLEASE submit a bug report"


def crashing_function(stderr: str) -> str | None:
    """The function LLVM was working on, from the stack dump, if any."""
    m = re.search(r"on function [\"']@?\"?([^\"'\s]+?)\"?[\"']", stderr)
    return m.group(1) if m else None


def strip_outputs(args: list[str]) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in OUTPUT_FLAGS_WITH_VALUE:
            skip = True
            continue
        if a in OUTPUT_FLAGS or a.startswith("-fcrash-diagnostics"):
            continue
        out.append(a)
    return out


def next_crash_dir(root: Path) -> Path:
    """crashes/.../<n>/, created atomically so parallel crashes don't clash."""
    root.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        d = root / str(n)
        try:
            d.mkdir()
            return d
        except FileExistsError:
            n += 1


def capture_crash(clang: Path, args: list[str], stderr: bytes,
                  invocation: list[str]) -> Path:
    """Save everything needed to reduce this crash with llvm-reduce."""
    d = next_crash_dir(Path(env("BENCH_CRASH_DIR")))
    cwd = Path.cwd()
    text = stderr.decode(errors="replace")
    sig = signature(text)
    func = crashing_function(text)
    (d / "stderr.txt").write_bytes(stderr)

    # Re-run exactly the crashing command.
    (d / "command.sh").write_text(
        "#!/bin/sh\n"
        f"# Called by the build as: {shlex.join(invocation)}\n"
        f"cd {shlex.quote(str(cwd))}\n"
        f"exec {shlex.join([str(clang), *args])}\n"
    )

    # Clang's own reproducer: preprocessed source plus a run script. This is
    # the only artifact we get when the frontend itself crashes.
    subprocess.run([str(clang), *args, f"-fcrash-diagnostics-dir={d}"],
                   capture_output=True)

    # IR as clang emits it before any LLVM pass runs. `-disable-llvm-passes`
    # keeps the opt level's attributes (no `optnone`), so compiling this IR
    # at the same opt level runs the same pipeline that crashed.
    inputs, _ = split_inputs(args)
    sources = [s for s in inputs if is_source(s)]
    base = strip_outputs([a for a in args if a not in sources])
    ir = d / "input.ll"
    ir_ok = False
    if len(sources) == 1:
        p = subprocess.run(
            [str(clang), *base, "-S", "-emit-llvm", "-Xclang",
             "-disable-llvm-passes", sources[0], "-o", str(ir)],
            capture_output=True)
        ir_ok = p.returncode == 0 and ir.is_file()
        if not ir_ok:
            ir.unlink(missing_ok=True)
            (d / "input.ll.log").write_bytes(p.stderr)

    # llvm-reduce calls this with a candidate .ll file. Exit 0 means the
    # candidate still hits the same crash. Without IR there is nothing for it
    # to test, so it is only written when input.ll exists.
    test = d / "interesting.sh"
    (d / "command.sh").chmod(0o755)
    reproduces = "no-ir"
    if ir_ok:
        test.write_text(
            "#!/bin/sh\n"
            "# Exit 0 iff compiling $1 still hits the original crash.\n"
            f"{shlex.join([str(clang), *base])} \\\n"
            "  -Wno-unused-command-line-argument -c -x ir \"$1\" -o /dev/null 2>&1 \\\n"
            f"  | grep -qF -- {shlex.quote(sig)}\n"
        )
        test.chmod(0o755)
        r = subprocess.run([str(test), str(ir)], capture_output=True)
        reproduces = "yes" if r.returncode == 0 else "no"

    files = {
        "stderr.txt": "the crash message and stack dump",
        "command.sh": "re-runs the exact crashing command",
        "input.ll": "IR before any LLVM pass ran",
        "interesting.sh": "test for llvm-reduce: exits 0 on the same crash",
    }
    readme = [
        f"Crash while compiling {', '.join(sources) or '(no single source)'}",
        f"  cwd:       {cwd}",
        f"  signature: {sig}",
        f"  function:  {func or '(unknown)'}",
        f"  IR reproduces crash: {reproduces}",
        "",
        "Files:",
    ]
    readme += [f"  {name:<15}{what}" for name, what in files.items()
               if (d / name).exists()]
    # Clang's reproducer: <stem>-<hash>.<ext> plus a matching .sh.
    readme += [f"  {f.name:<15}clang's reproducer"
               for f in sorted(d.iterdir()) if f.name not in files
               and f.name not in ("README", "input.ll.log")]
    readme.append("")
    llvm = clang.parent
    if ir_ok:
        readme += [
            "Reduce the IR:",
            f"  {llvm}/llvm-reduce --test={test} {ir} -o reduced.ll",
        ]
        if func:
            readme += [
                "",
                "Or first cut the IR down to the crashing function:",
                f"  {llvm}/llvm-extract --func={func} {ir} -S -o func.ll",
                f"  {test} func.ll && {llvm}/llvm-reduce --test={test} func.ll",
            ]
        if reproduces == "no":
            readme += [
                "",
                "Note: input.ll did not reproduce the crash. It may depend on",
                "a flag that only applies to source input, or on the frontend.",
            ]
    elif len(sources) != 1:
        readme += [
            "No IR: the command compiles several sources at once. Run",
            "command.sh with -v to find the crashing one.",
        ]
    else:
        readme += [
            "No IR: the crash happens before or during IR generation",
            "(see input.ll.log). Reduce clang's preprocessed reproducer with",
            "cvise or creduce instead.",
        ]
    (d / "README").write_text("\n".join(readme) + "\n")

    locked_append(
        d.parent / "index.tsv",
        "\t".join([d.name, env("BENCH_ROUND", "1"), ",".join(sources),
                   reproduces, sig]) + "\n")
    return d


# --- main -------------------------------------------------------------------


def main() -> int:
    invoked_as = os.environ.get("BENCH_INVOKED_AS") or Path(sys.argv[0]).name
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
    crashed = proc.returncode != 0 and (
        proc.returncode < 0 or CRASH_RE.search(proc.stderr) is not None)

    crash_dir = None
    if crashed and env("BENCH_CRASH_DIR", ""):
        crash_dir = capture_crash(clang, args, proc.stderr, sys.argv)

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
        "crash": str(crash_dir) if crash_dir else None,
    }
    locked_append(data / "compile.jsonl", json.dumps(record) + "\n")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
