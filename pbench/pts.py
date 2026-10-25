"""Thin layer over the Phoronix Test Suite (PTS) command line."""

import functools
import os
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import Config, Variant
from .layout import Layout, opt_name

REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "toolchain" / "wrapper.py"
SHIM_NAMES = ["cc", "gcc", "clang", "c++", "g++", "clang++", "nasm", "yasm"]
PTS_USER_DIR = Path.home() / ".phoronix-test-suite"


def pts_bin(cfg: Config) -> Path:
    """The PTS launcher. Always run it with cwd=cfg.pts: on macOS it takes
    its own install dir from the current directory."""
    return cfg.pts / "phoronix-test-suite"


def make_shims(layout: Layout) -> Path:
    """A shim per compiler name that runs the wrapper.

    This dir goes first on PATH. A build file that hardcodes `gcc` instead of
    using `$CC` still reaches our clang, and the wrapper records the name it
    was called as. The shims run the wrapper with this Python rather than
    `python3` from PATH, which may be too old for it.
    """
    d = layout.shims
    d.mkdir(parents=True, exist_ok=True)
    for name in SHIM_NAMES:
        shim = d / name
        if shim.is_symlink() or shim.exists():
            shim.unlink()
        shim.write_text(
            "#!/bin/sh\n"
            f"BENCH_INVOKED_AS={name} exec {shlex.quote(sys.executable)} "
            f"{shlex.quote(str(WRAPPER))} \"$@\"\n")
        shim.chmod(0o755)
    return d


def link_test_profiles(cfg: Config) -> None:
    """Point ~/.phoronix-test-suite/test-profiles at the configured repo.

    PTS only looks for test profiles there. An existing symlink is
    re-pointed, so switching configs switches profile checkouts. A real
    directory is left alone, because it may hold the user's own profiles.
    """
    link = PTS_USER_DIR / "test-profiles"
    PTS_USER_DIR.mkdir(exist_ok=True)
    if link.is_symlink():
        if link.resolve() == cfg.test_profiles.resolve():
            return
        print(f"note: re-pointing {link} -> {cfg.test_profiles}")
        link.unlink()
    elif link.exists():
        sys.exit(f"error: {link} is a real directory; move it away and "
                 f"rerun, so it can link to {cfg.test_profiles}")
    link.symlink_to(cfg.test_profiles)


def batch_setup(cfg: Config) -> None:
    """Answer PTS's batch-mode questions once, as run-all.sh did."""
    answers = "\n".join([
        "y",  # save test results when in batch mode
        "n",  # open the web browser automatically
        "n",  # auto upload results to OpenBenchmarking.org
        "n",  # prompt for test identifier
        "n",  # prompt for test description
        "n",  # prompt for saved results file-name
        "y",  # run all test options
    ]) + "\n"
    subprocess.run([str(pts_bin(cfg)), "batch-setup"], input=answers,
                   text=True, stdout=subprocess.DEVNULL, check=True,
                   cwd=cfg.pts)


def results_name(cfg: Config, opt: str) -> str:
    """Name of the PTS result file, sanitized like PTS's clean_save_name:
    spaces become dashes, anything but ASCII letters, digits and dashes is
    dropped, repeated dashes collapse, lowercase, at most 126 chars."""
    raw = f"pbench-{cfg.name}-{opt_name(opt)}".strip().replace(" ", "-")
    kept = "".join(c for c in raw if c.isascii() and (c.isalnum() or c == "-"))
    return re.sub("-+", "-", kept).lower()[:126]


@functools.cache
def sdkroot() -> str | None:
    """The macOS SDK path. A self-built clang needs it to find libc headers."""
    if sys.platform != "darwin" or os.environ.get("SDKROOT"):
        return None
    p = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True,
                       text=True)
    return p.stdout.strip() or None


def env(cfg: Config, layout: Layout, test: str, variant: Variant, opt: str,
        rnd: int, cores: int, force_unsupported: bool = False) -> dict:
    """Environment for one PTS call: install or run of (test, variant, opt)."""
    shims = layout.shims
    e = dict(os.environ)
    flags = variant.flags
    if variant.inline_replay_from:
        # Replay the inlining decisions the other variant made on this test.
        remarks = layout.data(test, variant.inline_replay_from, opt)
        flags += (" -mllvm -cgscc-inline-replay="
                  + shlex.quote(str(remarks / "inline-remarks.txt")))
    e.update({
        "PATH": f"{shims}{os.pathsep}{e.get('PATH', '')}",
        "CC": str(shims / "clang"),
        "CXX": str(shims / "clang++"),
        "CFLAGS": f"{variant.flags} {opt}".strip(),
        "CXXFLAGS": f"{variant.flags} {opt}".strip(),
        "NUM_CPU_CORES": str(cores),
        "PIN_CMD": cfg.pin_cmd,
        "PTS_SILENT_MODE": "TRUE",
        "PTS_TEST_INSTALL_ROOT_PATH": f"{layout.install_root(variant.name, opt)}/",
        # PTS has its own gcc/cc masking, but only for tests that declare
        # `build-utilities`. Our shims cover every test, so turn it off.
        "NO_COMPILER_MASK": "1",
        # The core count differs between install and run; don't cache it.
        "NO_PHODEVI_CACHE": "1",
        "TEST_RESULTS_NAME": results_name(cfg, opt),
        "TEST_RESULTS_IDENTIFIER": variant.name,
        # Read by toolchain/wrapper.py.
        "BENCH_LLVM_PATH": str(variant.llvm_path),
        "BENCH_FLAGS": flags,
        "BENCH_OPT": opt,
        "BENCH_ROUND": str(rnd),
        "BENCH_DATA_DIR": str(layout.data(test, variant.name, opt)),
        "BENCH_CRASH_DIR": (str(layout.crashes(test, variant.name, opt))
                            if cfg.crash_capture else ""),
        "BENCH_DROP_FLAGS": "\n".join(cfg.drop_flags),
        "BENCH_INLINE_REMARKS": "1" if cfg.inline_remarks else "0",
        "BENCH_SHIM_DIR": str(shims),
    })
    if root := sdkroot():
        e["SDKROOT"] = root
    if force_unsupported:
        e["SKIP_TEST_SUPPORT_CHECKS"] = "1"
    e.update(cfg.env)
    return e


def run_logged(cmd: list[str], cwd: Path, env: dict, log: Path,
               verbose: bool) -> int:
    """Run `cmd`, writing its output to `log` (and the terminal if verbose)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "wb") as f:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL)
        for chunk in iter(lambda: p.stdout.read1(65536), b""):
            f.write(chunk)
            if verbose:
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
        return p.wait()


def install(cfg: Config, test: str, env: dict, log: Path,
            verbose: bool) -> bool:
    """Install one test. True if PTS considers it installed."""
    root = Path(env["PTS_TEST_INSTALL_ROOT_PATH"])
    install_dir = root / test
    shutil.rmtree(install_dir, ignore_errors=True)
    # PTS silently ignores PTS_TEST_INSTALL_ROOT_PATH unless it exists.
    root.mkdir(parents=True, exist_ok=True)
    run_logged([str(pts_bin(cfg)), "batch-install", test], cfg.pts, env,
               log, verbose)
    # PTS exits 0 even when install.sh fails, and it rewrites
    # pts-install.json after a failure too. What it only writes on failure
    # is install-failed.log, a copy of the log.
    return ((install_dir / "pts-install.json").is_file()
            and not (install_dir / "install-failed.log").is_file())


def run(cfg: Config, test: str, env: dict, log: Path, verbose: bool) -> int:
    return run_logged([str(pts_bin(cfg)), "batch-run", test], cfg.pts, env,
                      log, verbose)


def result_file(cfg: Config, opt: str) -> Path:
    return PTS_USER_DIR / "test-results" / results_name(cfg, opt) / "composite.xml"


def clear_results(cfg: Config, opt: str) -> None:
    shutil.rmtree(result_file(cfg, opt).parent, ignore_errors=True)


def supported_platforms(cfg: Config, test: str) -> list[str] | None:
    """`SupportedPlatforms` of a test, or None if it doesn't restrict them."""
    xml = cfg.test_profiles / test / "test-definition.xml"
    node = ET.parse(xml).getroot().find(".//SupportedPlatforms")
    if node is None or not (node.text or "").strip():
        return None
    return [p.strip() for p in node.text.split(",")]


def host_platform() -> str:
    """The name PTS uses for this OS in `SupportedPlatforms`."""
    return {"darwin": "MacOSX", "linux": "Linux"}.get(sys.platform,
                                                       sys.platform)


def is_supported(cfg: Config, test: str) -> bool:
    platforms = supported_platforms(cfg, test)
    return platforms is None or host_platform() in platforms
