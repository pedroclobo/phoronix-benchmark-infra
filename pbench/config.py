"""Experiment configuration.

One TOML file describes a whole experiment: which compiler variants to
compare, which tests to build, which optimization levels to use and where
results go. See `configs/example.toml` for an annotated example.

A `[host.<hostname>]` table overrides any key on the matching machine. This
lets one config work on, say, an x86 server and a MacBook, where only paths
and core counts differ.
"""

import os
import socket
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Flags that the wrapper removes from every compiler invocation. They either
# break the build with clang (`-Werror`, GCC-only flags) or add noise to the
# measurements (`-fprofile-use`). This is the list `toolchain/clang` had.
DEFAULT_DROP_FLAGS = [
    "-V",
    "-Wall",
    "-Werror",
    "-Wextra",
    "-fprofile-correction",
    "-fprofile-use",
    "-march=rv64gcv1p0",
    "-matomics",
    "-menable-experimental-extensions",
    "-mno-avx256-split-unaligned-load",
    "-mno-avx256-split-unaligned-store",
    "-pedantic",
    "-wd654",
]


class ConfigError(Exception):
    pass


@dataclass
class Variant:
    """One compiler under test, e.g. a baseline and a patched LLVM build."""

    name: str
    llvm_path: Path
    flags: str = ""
    label: str = ""
    color: str = ""
    # Name of an earlier variant whose inline remarks this one replays.
    inline_replay_from: str = ""


@dataclass
class Config:
    path: Path
    name: str
    tests: list[str]
    opt_levels: list[str]
    install_rounds: int
    output_dir: Path
    pts: Path
    test_profiles: Path
    build_jobs: int
    run_cpu_cores: int
    pin_cmd: str
    inline_remarks: bool
    asm_diff: bool
    asm_diff_timeout: int
    crash_capture: bool
    drop_flags: list[str]
    results_repo: Path | None
    results_repo_push: bool
    env: dict[str, str]
    variants: list[Variant]
    host: str = field(default_factory=lambda: hostname())

    @property
    def baseline(self) -> Variant:
        """The first variant. Every other variant is compared against it."""
        return self.variants[0]

    def variant(self, name: str) -> Variant:
        for v in self.variants:
            if v.name == name:
                return v
        raise ConfigError(f"unknown variant: {name}")

    @staticmethod
    def load(path: Path) -> "Config":
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        raw = apply_host_overrides(raw, hostname())
        return parse(raw, path)


def hostname() -> str:
    return socket.gethostname().split(".")[0]


def expand(p: str, base: Path) -> Path:
    """Expand `~` and env vars. Relative paths are relative to the config."""
    q = Path(os.path.expandvars(os.path.expanduser(p)))
    return q if q.is_absolute() else (base / q).resolve()


def deep_merge(dst: dict, src: dict) -> dict:
    out = dict(dst)
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_host_overrides(raw: dict, host: str) -> dict:
    """Merge `[host.<host>]` into the top level.

    Variants live in an array, so they can't be merged by position. Instead,
    `[host.<host>.variant.<name>]` is merged into the variant called `<name>`.
    """
    hosts = raw.pop("host", {})
    override = dict(hosts.get(host, {}))
    variant_overrides = override.pop("variant", {})
    raw = deep_merge(raw, override)
    for v in raw.get("variant", []):
        if v.get("name") in variant_overrides:
            v.update(variant_overrides[v["name"]])
    return raw


def normalize_opt(opt: str) -> str:
    """Accept both "O3" and "-O3", always return "-O3"."""
    opt = opt.strip()
    return opt if opt.startswith("-") else f"-{opt}"


def parse(raw: dict, path: Path) -> Config:
    base = path.parent.resolve()

    def need(table: dict, key: str, where: str):
        if key not in table:
            raise ConfigError(f"{path}: missing `{key}` in {where}")
        return table[key]

    # Tests come either inline or from a file with one test per line, the
    # format of the old `profiles.txt`.
    tests = list(raw.get("tests", []))
    if "tests_file" in raw:
        tests_file = expand(raw["tests_file"], base)
        for line in tests_file.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                tests.append(line)
    if not tests:
        raise ConfigError(f"{path}: no tests given (`tests` or `tests_file`)")

    paths = need(raw, "paths", "the top level")
    build = raw.get("build", {})
    run = raw.get("run", {})
    features = raw.get("features", {})
    wrapper = raw.get("wrapper", {})
    repo = raw.get("results_repo", {})

    variants = []
    for v in need(raw, "variant", "the top level"):
        variants.append(
            Variant(
                name=need(v, "name", "[[variant]]"),
                llvm_path=expand(need(v, "llvm_path", "[[variant]]"), base),
                flags=v.get("flags", ""),
                label=v.get("label", v["name"]),
                color=v.get("color", ""),
                inline_replay_from=v.get("inline_replay_from", ""),
            )
        )

    cfg = Config(
        path=path.resolve(),
        name=raw.get("name", path.stem),
        tests=tests,
        opt_levels=[normalize_opt(o) for o in raw.get("opt_levels", ["-O3"])],
        install_rounds=int(raw.get("install_rounds", 3)),
        output_dir=expand(need(raw, "output_dir", "the top level"), base),
        pts=expand(need(paths, "pts", "[paths]"), base),
        test_profiles=expand(need(paths, "test_profiles", "[paths]"), base),
        build_jobs=int(build.get("jobs", os.cpu_count() or 1)),
        run_cpu_cores=int(run.get("cpu_cores", 1)),
        pin_cmd=run.get("pin_cmd", ""),
        inline_remarks=bool(features.get("inline_remarks", False)),
        asm_diff=bool(features.get("asm_diff", True)),
        asm_diff_timeout=int(features.get("asm_diff_timeout", 600)),
        crash_capture=bool(features.get("crash_capture", True)),
        drop_flags=list(wrapper.get("drop_flags", DEFAULT_DROP_FLAGS)),
        results_repo=expand(repo["path"], base) if repo.get("path") else None,
        results_repo_push=bool(repo.get("push", True)),
        env={k: str(v) for k, v in raw.get("env", {}).items()},
        variants=variants,
    )
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    names = [v.name for v in cfg.variants]
    if len(set(names)) != len(names):
        raise ConfigError(f"{cfg.path}: duplicate variant names: {names}")
    for i, v in enumerate(cfg.variants):
        if not v.inline_replay_from:
            continue
        # Replay reads the remarks file that the other variant wrote during
        # its own install, so that variant must exist, come first, and
        # record remarks.
        earlier = names[:i]
        if v.inline_replay_from not in earlier:
            raise ConfigError(
                f"{cfg.path}: variant `{v.name}` replays inline remarks from "
                f"`{v.inline_replay_from}`, which must be an earlier variant"
            )
        if not cfg.inline_remarks:
            raise ConfigError(
                f"{cfg.path}: `inline_replay_from` needs "
                "`features.inline_remarks = true`"
            )
    if cfg.install_rounds < 1:
        raise ConfigError(f"{cfg.path}: install_rounds must be >= 1")


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)
