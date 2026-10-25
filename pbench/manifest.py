"""`run.json`: what exactly produced the results in an output dir."""

import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import Config
from .layout import Layout

REPO = Path(__file__).resolve().parent.parent


def git_head(path: Path) -> str | None:
    p = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return p.stdout.strip() or None


def clang_version(llvm: Path) -> str | None:
    """`clang --version`. It includes the LLVM commit if the build has it."""
    try:
        p = subprocess.run([str(llvm / "clang"), "--version"],
                           capture_output=True, text=True, timeout=30)
    except OSError:
        return None
    return p.stdout.strip() or None


def write(cfg: Config, layout: Layout) -> None:
    layout.root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "command": sys.argv,
        "date": datetime.now().isoformat(timespec="seconds"),
        "host": cfg.host,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "config_path": str(cfg.path),
        "config": cfg.path.read_text(),
        "bench_commit": git_head(REPO),
        "test_profiles_commit": git_head(cfg.test_profiles),
        "pts_commit": git_head(cfg.pts),
        "opt_levels": cfg.opt_levels,
        "variants": [
            {
                "name": v.name,
                "llvm_path": str(v.llvm_path),
                "flags": v.flags,
                "inline_replay_from": v.inline_replay_from,
                "clang_version": clang_version(v.llvm_path),
            }
            for v in cfg.variants
        ],
    }
    layout.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
