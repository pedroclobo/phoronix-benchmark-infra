#!/usr/bin/env python3
"""Benchmark clang variants with the Phoronix Test Suite.

    bench.py doctor  CONFIG     check the setup
    bench.py install CONFIG     only build the tests (and capture crashes)
    bench.py run     CONFIG     build, measure, benchmark and report
    bench.py prepare on|off     reduce benchmark noise (Linux, needs sudo)

See README.md and configs/example.toml.
"""

import argparse
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("bench.py needs Python 3.11+ (for tomllib)")

from pbench.commands import cmd_install, cmd_prepare, cmd_run
from pbench.config import Config, ConfigError
from pbench.doctor import cmd_doctor


def add_selection(p: argparse.ArgumentParser) -> None:
    p.add_argument("config", type=Path, help="experiment config (TOML)")
    p.add_argument("--only", nargs="+", metavar="TEST",
                   help="only these tests, e.g. `z3` or `local/z3`")
    p.add_argument("--variant", nargs="+", metavar="NAME",
                   help="only these variants")
    p.add_argument("--opt", nargs="+", metavar="LEVEL",
                   help="only these opt levels, e.g. O2")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="stream PTS output to the terminal")
    p.add_argument("--force-unsupported", action="store_true",
                   help="also build tests whose SupportedPlatforms lacks "
                        "this OS (sets SKIP_TEST_SUPPORT_CHECKS=1)")
    p.add_argument("--no-audit", action="store_true",
                   help="skip the check for objects not built by our clang")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="check tools, paths and LLVM builds")
    p.add_argument("config", type=Path)

    p = sub.add_parser(
        "install", help="only build the tests",
        description="Build each selected (test, variant, opt) once. Nothing "
                    "is benchmarked and no results repo is touched. Each "
                    "build ends as ok, build-failed, crashed or "
                    "foreign-objects; crashes leave reproducers under "
                    "<output_dir>/crashes/.")
    add_selection(p)

    p = sub.add_parser(
        "run", help="build, measure, benchmark and report",
        description="For each test: build each variant `install_rounds` "
                    "times, measure sizes, run the benchmark, diff the asm "
                    "against the baseline, regenerate the report and commit "
                    "to the results repo if one is configured.")
    add_selection(p)
    p.add_argument("-p", "--prepare", action="store_true",
                   help="run `prepare on` first (Linux, needs sudo)")
    p.add_argument("--no-report", action="store_true",
                   help="don't regenerate CSVs and plots after each test")
    p.add_argument("--no-repo", action="store_true",
                   help="ignore the configured results repo")
    p.add_argument("--no-push", action="store_true",
                   help="commit to the results repo but don't push")

    p = sub.add_parser("prepare", help="reduce benchmark noise (Linux)")
    p.add_argument("state", choices=["on", "off"])

    args = ap.parse_args()
    if args.cmd == "prepare":
        return cmd_prepare(args.state)
    try:
        cfg = Config.load(args.config)
    except (ConfigError, OSError) as e:
        sys.exit(f"error: {e}")

    if args.cmd == "doctor":
        return cmd_doctor(cfg, args)
    if args.cmd == "install":
        return cmd_install(cfg, args)
    if args.cmd == "run":
        return cmd_run(cfg, args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
