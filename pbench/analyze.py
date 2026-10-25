"""Post-install analysis: sizes, function sizes, asm diff and the audit.

All binary inspection uses the LLVM tools next to the baseline's clang
(`llvm-size`, `llvm-nm`, `llvm-objdump`). They read both ELF and Mach-O and
print the same format on Linux and macOS, unlike the system `size`, `nm` and
`objdump`.
"""

import bisect
import hashlib
import json
import platform
import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ELF = b"\x7fELF"
MACHO = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe")
BITCODE = (b"BC\xc0\xde", b"\xde\xc0\x17\x0b")


def magic(path: Path) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(4)
    except OSError:
        return b""


def is_binary(path: Path) -> bool:
    """ELF or Mach-O: objects, executables and shared libraries."""
    m = magic(path)
    return m == ELF or m in MACHO


def is_macho(path: Path) -> bool:
    return magic(path) in MACHO


def is_object_file(path: Path) -> bool:
    """A compiled object, including LLVM bitcode from -flto."""
    return path.suffix in (".o", ".obj") and (is_binary(path)
                                              or magic(path) in BITCODE)


# --- compile.jsonl ----------------------------------------------------------


@dataclass
class Compiles:
    """What the wrapper recorded during the last install round."""

    records: list[dict] = field(default_factory=list)

    @staticmethod
    def load(data_dir: Path) -> "Compiles":
        f = data_dir / "compile.jsonl"
        if not f.is_file():
            return Compiles()
        recs = [json.loads(l) for l in f.read_text().splitlines() if l]
        last = max((r["round"] for r in recs), default=1)
        return Compiles([r for r in recs if r["round"] == last])

    def produced(self) -> tuple[set[str], set[str]]:
        """Paths and content hashes of every file the wrappers produced."""
        paths, hashes = set(), set()
        for r in self.records:
            for o in r.get("outputs", []):
                paths.add(o["path"])
                hashes.add(o["hash"])
        return paths, hashes

    def compiled_binaries(self, install_dir: Path) -> list[Path]:
        """Binaries produced by a compile step, i.e. from C/C++ sources.

        Link-only steps (all inputs are objects) are skipped so the same code
        isn't counted twice, once in the .o and again in the executable. A
        one-step `cc *.c -o prog` build still counts, through `prog`.
        """
        root = install_dir.resolve()
        out = set()
        for r in self.records:
            if r["kind"] != "cc" or r["rc"] != 0 or not r["sources"]:
                continue
            for o in r["outputs"]:
                p = Path(o["path"])
                if (p.is_relative_to(root) and p.is_file() and is_binary(p)
                        and not is_cmake_probe(p)):
                    out.add(p)
        return sorted(out)

    def invoked_as(self) -> Counter:
        return Counter(r["invoked_as"] for r in self.records)

    def crashes(self) -> list[str]:
        return [r["crash"] for r in self.records if r.get("crash")]


def is_cmake_probe(path: Path) -> bool:
    """CMake's compiler checks, e.g. CMakeFiles/<ver>/CompilerIdC/a.out.
    They stay in the build tree but aren't part of the program."""
    return any(part.startswith("CompilerId") or part in ("CMakeTmp",
                                                         "CMakeScratch")
               for part in path.parts)


def audit(install_dir: Path, compiles: Compiles) -> list[Path]:
    """Object files under `install_dir` that no wrapper produced.

    Those were built by a compiler we don't control, for example a build file
    calling `/usr/bin/cc` by absolute path. Objects that were renamed or
    copied after the build are matched by content hash.
    """
    paths, hashes = compiles.produced()
    foreign = []
    for p in install_dir.rglob("*"):
        if not p.is_file() or not is_object_file(p):
            continue
        if str(p.resolve()) in paths:
            continue
        h = hashlib.blake2b(p.read_bytes(), digest_size=16).hexdigest()
        if h not in hashes:
            foreign.append(p)
    return sorted(foreign)


# --- sizes ------------------------------------------------------------------


def object_sizes(llvm: Path, binaries: list[Path]) -> list[tuple[int, Path]]:
    """`text` bytes of each binary: code plus read-only data.

    On ELF this is the `text` column of berkeley-format llvm-size, which is
    what `size` reported before.
    """
    macho = [b for b in binaries if is_macho(b)]
    elf = [b for b in binaries if not is_macho(b)]
    out = [(macho_text_size(llvm, b), b) for b in macho]
    for i in range(0, len(elf), 200):
        chunk = elf[i:i + 200]
        p = subprocess.run(
            [str(llvm / "llvm-size"), "--format=berkeley", *map(str, chunk)],
            capture_output=True, text=True)
        for line in p.stdout.splitlines()[1:]:
            row = line.split("\t")
            if not row[0].strip().isdigit():
                continue
            # Columns are tab-separated and the file name comes last. With a
            # single input, llvm-size leaves the name out.
            path = chunk[0] if len(chunk) == 1 else Path(row[-1].strip())
            out.append((int(row[0].strip()), path))
    return out


def macho_text_size(llvm: Path, binary: Path) -> int:
    """Sum of the sections in the `__TEXT` segment.

    The berkeley `__TEXT` column is the segment size, which linked images
    round up to whole 16 KiB pages. Summing the sections avoids that.
    Objects print `Section (__TEXT, __text): N`, linked images print
    `Segment __TEXT: N` followed by `Section __text: N`.
    """
    p = subprocess.run([str(llvm / "llvm-size"), "-m", str(binary)],
                       capture_output=True, text=True)
    total, in_text = 0, False
    for line in p.stdout.splitlines():
        line = line.strip()
        if line.startswith("Segment "):
            in_text = line.startswith("Segment __TEXT:")
        elif m := re.match(r"Section \(__TEXT, \w+\): (\d+)", line):
            total += int(m.group(1))
        elif in_text and (m := re.match(r"Section \w+: (\d+)", line)):
            total += int(m.group(1))
    return total


def function_sizes(llvm: Path, binary: Path) -> dict[str, int]:
    """Size in bytes of every function defined in `binary`."""
    if is_macho(binary):
        return macho_function_sizes(llvm, binary)
    p = subprocess.run(
        [str(llvm / "llvm-nm"), "--defined-only", "-S", "-t", "d",
         str(binary)], capture_output=True, text=True)
    sizes = {}
    for line in p.stdout.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) == 4 and parts[2] in ("T", "t"):
            sizes[parts[3]] = int(parts[1])
    return sizes


# Assembler-local labels that share an address with a real function in
# Mach-O objects (`ltmp0` marks the start of a section).
NOT_FUNCTIONS = re.compile(r"^(ltmp\d+|l_.*|L.*|__mh_\w+_header)$")


def macho_text_symbols(llvm: Path, binary: Path) -> tuple[list, int | None]:
    """Sorted (address, name) of functions in `__TEXT,__text`, and its end.

    When several symbols share an address, the real function name wins over
    assembler labels like `ltmp0`.
    """
    p = subprocess.run(
        [str(llvm / "llvm-nm"), "--defined-only", "-n", "-t", "d", "-m",
         str(binary)], capture_output=True, text=True)
    by_addr: dict[int, str] = {}
    for line in p.stdout.splitlines():
        m = re.match(r"(\d+) \(__TEXT,__text\) .*?(\S+)$", line)
        if not m:
            continue
        addr, name = int(m.group(1)), m.group(2)
        if NOT_FUNCTIONS.match(name):
            by_addr.setdefault(addr, "")
        elif not by_addr.get(addr):
            by_addr[addr] = name
    h = subprocess.run([str(llvm / "llvm-objdump"), "-h", str(binary)],
                       capture_output=True, text=True)
    end = None
    for line in h.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "__text":
            end = int(parts[3], 16) + int(parts[2], 16)
    # Labels without a function name still bound the previous function.
    return sorted(by_addr.items()), end


def macho_function_sizes(llvm: Path, binary: Path) -> dict[str, int]:
    """Mach-O symbols carry no size (`nm -S` prints 0 for all of them).

    A function's size is the gap to the next symbol in `__TEXT,__text`. The
    last one runs to the end of the section.
    """
    syms, end = macho_text_symbols(llvm, binary)
    sizes = {}
    for (addr, name), (nxt, _) in zip(syms, syms[1:] + [(end, "")]):
        if name and nxt is not None and nxt > addr:
            sizes[name] = nxt - addr
    return sizes


def write_sizes(llvm: Path, binaries: list[Path], install_dir: Path,
                data_dir: Path) -> None:
    rows = object_sizes(llvm, binaries)
    with open(data_dir / "object-size.tsv", "w") as f:
        for text, path in rows:
            f.write(f"{text}\t{path.relative_to(install_dir.resolve())}\n")
    funcs = set()
    for b in binaries:
        for name, size in function_sizes(llvm, b).items():
            funcs.add((size, name))
    with open(data_dir / "functions.tsv", "w") as f:
        for size, name in sorted(funcs):
            f.write(f"{size}\t{name}\n")


# --- asm diff ---------------------------------------------------------------


# Operands like `bl 0x18 <_h+0x10>` or `adrp x0, <_main+0x240>`.
SYMBOLIC = re.compile(r"(?:\b0x[0-9a-f]+ )?<([^>+]+)(\+0x[0-9a-f]+)?>")


def normalize(insn: str, func: str) -> str:
    """Drop what moves when unrelated code changes size.

    Absolute addresses always go. Offsets into *other* symbols go too: in a
    linked image they point at stubs or data whose position depends on the
    layout of everything else. Offsets into the current function stay, since
    a branch to a different place in it is a real change.
    """
    def repl(m: re.Match) -> str:
        sym, off = m.group(1), m.group(2) or ""
        return f"<{sym}{off}>" if sym == func else f"<{sym}>"
    return SYMBOLIC.sub(repl, insn)


def disassemble(llvm: Path, binary: Path) -> dict[str, list[str]]:
    """Map each function name to its instructions, without addresses.

    Without addresses and raw bytes, the same code at a different offset
    still compares equal.
    """
    cmd = [str(llvm / "llvm-objdump"), "-d", "--no-show-raw-insn"]
    if platform.machine() in ("x86_64", "AMD64"):
        cmd.append("--x86-asm-syntax=intel")  # as run-all.sh's -Mintel
    macho = is_macho(binary)
    if not macho:
        cmd.append("--no-addresses")
    p = subprocess.run([*cmd, str(binary)], capture_output=True, text=True)
    if macho:
        return split_by_address(p.stdout, macho_text_symbols(llvm, binary)[0])
    return split_by_header(p.stdout)


def split_by_header(text: str) -> dict[str, list[str]]:
    """ELF: llvm-objdump prints a `<name>:` header per function."""
    funcs, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^<(.+)>:$", line)
        if m:
            name = m.group(1)
            cur = funcs.setdefault(name, [])
        elif line.startswith("Disassembly of section"):
            cur = None
        elif cur is not None and line.strip():
            cur.append(normalize(line.strip(), name))
    return funcs


def split_by_address(text: str, syms: list) -> dict[str, list[str]]:
    """Mach-O: headers may name `ltmp0` instead of the function, so assign
    each instruction to the function whose start address precedes it.

    Only `__TEXT,__text` counts. Linked images also have `__stubs` right
    after it, which would otherwise end up in the last function.
    """
    starts = [a for a, _ in syms]
    funcs: dict[str, list[str]] = {}
    in_text = False
    for line in text.splitlines():
        if line.startswith("Disassembly of section"):
            in_text = line.rstrip(":").endswith("__TEXT,__text")
            continue
        m = re.match(r"^\s*([0-9a-f]+):\s*(.*)$", line) if in_text else None
        if not m:
            continue
        i = bisect.bisect_right(starts, int(m.group(1), 16)) - 1
        if i < 0 or not syms[i][1]:
            continue
        name = syms[i][1]
        funcs.setdefault(name, []).append(normalize(m.group(2).strip(), name))
    return funcs


def asm_diff(llvm: Path, base_dir: Path, base_bins: list[Path],
             other_dir: Path, timeout_s: int) -> dict:
    """Compare every function of the baseline with the other variant.

    - strict: the instructions differ at all.
    - loose: the instruction count differs. The old Bash version counted the
      added and removed lines of a `diff`. Those counts differ exactly when
      the line counts differ, so this is the same test, just faster.
    """
    deadline = time.monotonic() + timeout_s
    all_funcs, strict, loose = set(), set(), set()
    timed_out = False
    base_root = base_dir.resolve()
    for b in base_bins:
        if time.monotonic() > deadline:
            timed_out = True
            break
        other = other_dir / b.relative_to(base_root)
        if not other.is_file():
            continue
        fa, fb = disassemble(llvm, b), disassemble(llvm, other)
        for name, insns in fa.items():
            all_funcs.add(name)
            if name not in fb or insns == fb[name]:
                continue
            strict.add(name)
            if len(insns) != len(fb[name]):
                loose.add(name)
    return {
        "functions": len(all_funcs),
        "strict": sorted(strict),
        "loose": sorted(loose),
        "timed_out": timed_out,
    }
