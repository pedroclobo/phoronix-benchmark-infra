"""The `install`, `run` and `prepare` subcommands."""

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import analyze, manifest, pts
from .config import Config, Variant
from .layout import Layout, opt_name, test_name
from .results_repo import ResultsRepo

REPO = Path(__file__).resolve().parent.parent

# Builds whose outputs can be measured and compared.
BUILT = ("ok", "foreign-objects")

# The names CC and CXX point to. Anything else in `invoked_as` means a build
# file called a compiler by a hardcoded name and our shim caught it.
EXPECTED_NAMES = {"clang", "clang++"}


@dataclass
class Selection:
    """The tests, variants and opt levels picked by --only/--variant/--opt."""

    tests: list[str]
    variants: list[Variant]
    opts: list[str]


def select(cfg: Config, args) -> Selection:
    tests = cfg.tests
    if args.only:
        wanted = set(args.only)
        tests = [t for t in tests if t in wanted or test_name(t) in wanted]
        unknown = wanted - set(tests) - {test_name(t) for t in tests}
        if unknown:
            sys.exit(f"error: not in the config's tests: {sorted(unknown)}")
    variants = cfg.variants
    if args.variant:
        variants = [cfg.variant(n) for n in args.variant]
    opts = cfg.opt_levels
    if args.opt:
        opts = [o if o.startswith("-") else f"-{o}" for o in args.opt]
    return Selection(tests, variants, opts)


# --- install ----------------------------------------------------------------


def install_one(cfg: Config, layout: Layout, test: str, variant: Variant,
                opt: str, rounds: int, args) -> dict:
    """Install (test, variant, opt) `rounds` times and audit the result.

    Returns the status that is also written to `status.json`: ok,
    build-failed, crashed, no-compiles, foreign-objects or unsupported.
    """
    data = layout.data(test, variant.name, opt)
    install_dir = layout.install_dir(test, variant.name, opt)
    shutil.rmtree(data, ignore_errors=True)
    shutil.rmtree(layout.crashes(test, variant.name, opt), ignore_errors=True)
    data.mkdir(parents=True)

    status = {"test": test, "variant": variant.name, "opt": opt_name(opt)}
    if not args.force_unsupported and not pts.is_supported(cfg, test):
        status["status"] = "unsupported"
        (data / "status.json").write_text(json.dumps(status, indent=2))
        print_status(status)
        return status

    if variant.inline_replay_from:
        remarks = layout.data(test, variant.inline_replay_from, opt)
        if not (remarks / "inline-remarks.txt").is_file():
            print(f"  warning: no inline remarks from "
                  f"{variant.inline_replay_from} for {test}; install it first")

    # Several rounds give a stable compile-time average. Every round starts
    # from a clean install dir, so each one rebuilds everything.
    start = time.monotonic()
    ok = False
    for rnd in range(1, rounds + 1):
        print(f"  {variant.name} {opt}: installing ({rnd}/{rounds})",
              flush=True)
        env = pts.env(cfg, layout, test, variant, opt, rnd, cfg.build_jobs,
                      args.force_unsupported)
        ok = pts.install(cfg, test, env, data / f"install-{rnd}.log",
                         args.verbose)
        if not ok:
            break

    compiles = analyze.Compiles.load(data)
    crashes = compiles.crashes()
    foreign = []
    if ok and not args.no_audit:
        foreign = analyze.audit(install_dir, compiles)
    hardcoded = {n: c for n, c in compiles.invoked_as().items()
                 if n not in EXPECTED_NAMES}

    if crashes:
        state = "crashed"
    elif not ok:
        state = "build-failed"
    elif not any(r["kind"] == "cc" and r["sources"] for r in compiles.records):
        # PTS only knows what install.sh reported. A script whose build step
        # failed without updating install-exit-status still looks installed.
        state = "no-compiles"
    elif foreign:
        state = "foreign-objects"
    else:
        state = "ok"
    status.update({
        "status": state,
        "seconds": round(time.monotonic() - start),
        "compiler_calls": len(compiles.records),
        "hardcoded_compiler_names": hardcoded,
        "foreign_object_count": len(foreign),
        "foreign_objects": [str(p.relative_to(install_dir))
                            for p in foreign[:100]],
        "crashes": crashes,
        "log": str(data / f"install-{rnd}.log"),
    })
    (data / "status.json").write_text(json.dumps(status, indent=2) + "\n")
    print_status(status)
    return status


def print_status(s: dict) -> None:
    line = f"  {s['variant']} -{s['opt']}: {s['status']}"
    if "seconds" in s:
        line += f" in {s['seconds']}s, {s['compiler_calls']} compiler calls"
    print(line)
    if s.get("hardcoded_compiler_names"):
        names = ", ".join(f"{n}×{c}" for n, c in
                          s["hardcoded_compiler_names"].items())
        print(f"    caught hardcoded compiler names: {names}")
    if s.get("foreign_objects"):
        print(f"    {s['foreign_object_count']} objects not built by our "
              f"clang, e.g. {s['foreign_objects'][0]}")
    for c in s.get("crashes", []):
        print(f"    crash reproducer: {c}")
    if s["status"] in ("build-failed", "no-compiles"):
        print(f"    log: {s['log']}")


def write_summaries(layout: Layout) -> None:
    """Rebuild install-summary.tsv and crashes/index.tsv from the per-install
    files, so partial reruns (--only) keep everyone else's rows."""
    rows = []
    for f in sorted((layout.root / "data").glob("*/*/*/status.json")):
        s = json.loads(f.read_text())
        rows.append("\t".join([test_name(s["test"]), s["variant"], s["opt"],
                               s["status"],
                               str(s.get("foreign_object_count", 0)),
                               ",".join(s.get("hardcoded_compiler_names",
                                              {}))]))
    layout.summary.write_text(
        "test\tvariant\topt\tstatus\tforeign_objects\thardcoded_names\n"
        + "".join(r + "\n" for r in rows))

    crash_root = layout.root / "crashes"
    lines = []
    for f in sorted(crash_root.glob("*/*/*/index.tsv")):
        variant, test, opt = f.parent.relative_to(crash_root).parts
        for line in f.read_text().splitlines():
            lines.append(f"{variant}\t{test}\t{opt}\t{line}\n")
    if crash_root.is_dir():
        (crash_root / "index.tsv").write_text(
            "variant\ttest\topt\tn\tround\tsource\tir_reproduces\tsignature\n"
            + "".join(lines))


def print_table(statuses: list[dict]) -> None:
    if not statuses:
        return
    print("\nSummary")
    w = max(len(test_name(s["test"])) for s in statuses)
    for s in statuses:
        print(f"  {test_name(s['test']):<{w}}  {s['variant']:<12} "
              f"-{s['opt']:<5} {s['status']}")
    bad = [s for s in statuses if s["status"] != "ok"]
    print(f"\n{len(statuses) - len(bad)}/{len(statuses)} ok")


def prepare_run(cfg: Config, layout: Layout) -> None:
    layout.root.mkdir(parents=True, exist_ok=True)
    pts.link_test_profiles(cfg)
    pts.make_shims(layout)
    pts.batch_setup(cfg)
    manifest.write(cfg, layout)


def cmd_install(cfg: Config, args) -> int:
    """Build every selected test once. No benchmarks, no results repo."""
    layout = Layout(cfg.output_dir)
    sel = select(cfg, args)
    prepare_run(cfg, layout)
    statuses = []
    for test in sel.tests:
        print(f"{test}", flush=True)
        for opt in sel.opts:
            for v in sel.variants:
                statuses.append(install_one(cfg, layout, test, v, opt, 1,
                                            args))
        write_summaries(layout)
    print_table(statuses)
    return 0 if all(s["status"] == "ok" for s in statuses) else 1


# --- run --------------------------------------------------------------------


def measure(cfg: Config, layout: Layout, test: str, variant: Variant,
            opt: str) -> None:
    """Object and function sizes of what the compile steps produced."""
    data = layout.data(test, variant.name, opt)
    install_dir = layout.install_dir(test, variant.name, opt)
    bins = analyze.Compiles.load(data).compiled_binaries(install_dir)
    analyze.write_sizes(cfg.baseline.llvm_path, bins, install_dir, data)


def is_built(layout: Layout, test: str, variant: Variant, opt: str) -> bool:
    """Whether the last install of (test, variant, opt) succeeded."""
    status = layout.data(test, variant.name, opt) / "status.json"
    return (status.is_file()
            and json.loads(status.read_text()).get("status") in BUILT)


def diff_asm(cfg: Config, layout: Layout, test: str, opt: str,
             variants: list[Variant]) -> None:
    """Compare each built variant's code with the baseline's, function by
    function. `variants` only holds variants whose build succeeded. The
    baseline may come from an earlier run (e.g. `run --variant byte`)."""
    base = cfg.baseline
    if not is_built(layout, test, base, opt):
        print("  asm diff skipped: no baseline build")
        return
    base_dir = layout.install_dir(test, base.name, opt)
    base_bins = analyze.Compiles.load(
        layout.data(test, base.name, opt)).compiled_binaries(base_dir)
    out = layout.asm_diff(test, opt)
    out.mkdir(parents=True, exist_ok=True)
    for v in variants:
        if v is base:
            continue
        print(f"  {v.name} {opt}: comparing asm with {base.name}", flush=True)
        result = analyze.asm_diff(base.llvm_path, base_dir, base_bins,
                                  layout.install_dir(test, v.name, opt),
                                  cfg.asm_diff_timeout)
        result["baseline"] = base.name
        (out / f"{v.name}.json").write_text(json.dumps(result, indent=1))


def run_report(cfg: Config, layout: Layout) -> None:
    """Regenerate CSVs and plots, if the plotting libraries are installed."""
    try:
        from report import build
    except ImportError as e:
        print(f"  report skipped ({e}); see requirements.txt")
        return
    build(cfg, layout)


def cmd_run(cfg: Config, args) -> int:
    """Install, measure, benchmark and report every selected test."""
    layout = Layout(cfg.output_dir)
    sel = select(cfg, args)
    if args.prepare:
        cmd_prepare("on")
    prepare_run(cfg, layout)
    repo = None
    if cfg.results_repo and not args.no_repo:
        repo = ResultsRepo(cfg, layout, push=not args.no_push)
        repo.start()

    statuses = []
    for test in sel.tests:
        print(f"{test}", flush=True)
        for opt in sel.opts:
            built = []
            for v in sel.variants:
                # Drop this variant's old results first, so a failed rebuild
                # can't leave stale numbers next to the new compile data.
                runtime = layout.test_results(test, v.name, opt)
                runtime.unlink(missing_ok=True)
                (layout.asm_diff(test, opt) / f"{v.name}.json").unlink(
                    missing_ok=True)

                s = install_one(cfg, layout, test, v, opt,
                                cfg.install_rounds, args)
                statuses.append(s)
                if s["status"] not in BUILT:
                    continue
                built.append(v)
                measure(cfg, layout, test, v, opt)
                print(f"  {v.name} {opt}: running benchmark", flush=True)
                # One PTS result file per variant, so rerunning one variant
                # (--variant) keeps the others' results.
                pts.clear_results(cfg, opt)
                env = pts.env(cfg, layout, test, v, opt, cfg.install_rounds,
                              cfg.run_cpu_cores, args.force_unsupported)
                pts.run(cfg, test, env,
                        layout.data(test, v.name, opt) / "run.log",
                        args.verbose)
                result = pts.result_file(cfg, opt)
                if result.is_file():
                    runtime.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(result, runtime)
                else:
                    print(f"  {v.name} {opt}: no PTS result at {result}")
            if cfg.asm_diff:
                diff_asm(cfg, layout, test, opt, built)
        write_summaries(layout)
        if not args.no_report:
            run_report(cfg, layout)
        if repo:
            repo.publish(f"{test}: {', '.join(opt_name(o) for o in sel.opts)}")
    print_table(statuses)
    return 0 if all(s["status"] == "ok" for s in statuses) else 1


# --- prepare ----------------------------------------------------------------


def cmd_prepare(state: str) -> int:
    """Reduce benchmark noise on Linux (turbo, SMT, governor, ASLR)."""
    if sys.platform != "linux":
        print(f"warning: `prepare` only supports Linux; on {sys.platform} "
              "nothing was changed, so expect noisier runtimes")
        return 0
    arg = "1" if state == "on" else "0"
    return subprocess.run([str(REPO / "prepare-benchmark-env.sh"),
                           arg]).returncode
