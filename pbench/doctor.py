"""`bench.py doctor`: catch setup problems before a multi-hour run."""

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from . import pts
from .config import Config

OK, WARN, FAIL = "ok", "warn", "FAIL"


class Report:
    def __init__(self):
        self.failed = False

    def __call__(self, level: str, msg: str) -> None:
        print(f"[{level:>4}] {msg}")
        if level == FAIL:
            self.failed = True


def runs(cmd: list[str]) -> tuple[bool, str]:
    """Whether `cmd` starts and exits 0, plus its first output line."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except OSError as e:
        return False, str(e)
    out = (p.stdout or p.stderr).strip().splitlines()
    return p.returncode == 0, out[0] if out else ""


def cmd_doctor(cfg: Config, args) -> int:
    r = Report()
    print(f"config {cfg.path} on host {cfg.host} ({sys.platform})\n")

    # PTS is a PHP program.
    if shutil.which("php"):
        r(OK, f"php: {runs(['php', '--version'])[1]}")
    else:
        hint = "brew install php" if sys.platform == "darwin" else \
            "install php-cli"
        r(FAIL, f"php not found ({hint})")
    exe = pts.pts_bin(cfg)
    r(OK if exe.is_file() else FAIL, f"PTS: {exe}")

    # PTS reads test profiles from ~/.phoronix-test-suite/test-profiles.
    link = pts.PTS_USER_DIR / "test-profiles"
    if link.is_symlink() and link.resolve() == cfg.test_profiles.resolve():
        r(OK, f"{link} -> {cfg.test_profiles}")
    elif link.exists() and not link.is_symlink():
        r(FAIL, f"{link} is a real directory; move it away so it can link "
                f"to {cfg.test_profiles}")
    else:
        r(WARN, f"{link} will be (re)linked to {cfg.test_profiles}")

    # Every variant's compiler must exist and start. A half-rebuilt LLVM
    # tree fails here with a dyld/ld.so error rather than mid-run.
    for v in cfg.variants:
        for driver in ("clang", "clang++"):
            ok, out = runs([str(v.llvm_path / driver), "--version"])
            r(OK if ok else FAIL, f"variant {v.name}: {driver}: {out}")

    # Analysis uses the baseline's LLVM tools. Crash reduction wants the
    # reducer tools, but builds work without them.
    llvm = cfg.baseline.llvm_path
    for tool in ("llvm-size", "llvm-nm", "llvm-objdump"):
        ok, out = runs([str(llvm / tool), "--version"])
        r(OK if ok else FAIL, f"{tool}: {'found' if ok else out}")
    for tool in ("llvm-reduce", "llvm-extract"):
        ok, _ = runs([str(llvm / tool), "--version"])
        r(OK if ok else WARN,
          f"{tool}: {'found' if ok else 'missing (only needed to reduce crashes)'}")

    # Each test must exist. Tests that don't list this OS are skipped unless
    # --force-unsupported is given.
    for test in cfg.tests:
        xml = cfg.test_profiles / test / "test-definition.xml"
        if not xml.is_file():
            r(FAIL, f"{test}: no {xml}")
            continue
        deps = ET.parse(xml).getroot().findtext(".//ExternalDependencies")
        deps = f" (needs: {deps})" if deps else ""
        if pts.is_supported(cfg, test):
            r(OK, f"{test}{deps}")
        else:
            r(WARN, f"{test}: SupportedPlatforms lacks {pts.host_platform()}; "
                    "skipped unless --force-unsupported")

    if cfg.results_repo:
        ok = (cfg.results_repo / ".git").exists()
        r(OK if ok else FAIL, f"results repo: {cfg.results_repo}")

    try:
        import matplotlib, numpy, pandas  # noqa: F401
        r(OK, "report: matplotlib, numpy and pandas importable")
    except ImportError as e:
        r(WARN, f"report: {e} (pip install -r requirements.txt)")

    if sys.platform == "darwin":
        r(WARN, "macOS: no CPU pinning or frequency control; runtimes are "
                "noisier than on a prepared Linux host")

    print("\nall good" if not r.failed else "\nfix the FAIL lines above")
    return 1 if r.failed else 0
