# Phoronix Benchmark Infrastructure

Scripts to compare clang builds on real programs, using the
[Phoronix Test Suite](https://github.com/phoronix-test-suite/phoronix-test-suite)
(PTS). For every test program and every compiler variant, they measure:

- compile time and peak compiler memory,
- size of the generated code, per binary and per function,
- which functions changed against the baseline (asm diff),
- run time of the benchmark.

They can also just build the programs and keep a reproducer of every clang
crash, ready for `llvm-reduce`.

Everything is driven by one experiment config. It works on Linux (x86) and
on macOS (Apple silicon).

## Setup

You need Python 3.11+, `php` (PTS is written in PHP), git, and checkouts of
PTS and of the test profiles:

```sh
git clone https://github.com/phoronix-test-suite/phoronix-test-suite.git
git clone https://github.com/pedroclobo/test-profiles.git --branch=clang
```

The custom profiles under `local/` make the tests build with clang. On
macOS, use the `feat/macos` branch of the test profiles until it is merged.

On macOS, install the tools PTS and the test builds need:

```sh
brew install php yasm nasm tcl-tk bison flex fftw autoconf automake libtool
```

Plots need matplotlib, numpy and pandas. Everything else uses only the
Python standard library.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

You don't need to link `~/.phoronix-test-suite/test-profiles` yourself:
`bench.py` points it at the test profiles of the config.

## Quick start

```sh
cp configs/example.toml my-experiment.toml   # then edit paths and variants
./bench.py doctor  my-experiment.toml        # check the setup
./bench.py install my-experiment.toml        # only build everything
./bench.py run     my-experiment.toml        # build, measure, benchmark
```

Run `bench.py` with the venv's Python (`.venv/bin/python bench.py ...`) to
get plots after every test.

## The config

One TOML file describes an experiment. `configs/example.toml` explains every
key. In short:

| Key | Meaning |
| --- | --- |
| `name` | Name of the experiment. |
| `tests` / `tests_file` | PTS tests to build, e.g. `local/z3`. |
| `opt_levels` | Every `-O<n>` in a compile is replaced by each of these. |
| `install_rounds` | Builds per test in `run`. Compile time is averaged. |
| `output_dir` | Where everything is written. |
| `[paths]` | `pts` and `test_profiles` checkouts. |
| `[build] jobs` | Parallel build jobs. |
| `[run] cpu_cores`, `pin_cmd` | Cores and pinning prefix for the benchmarks. |
| `[features]` | `inline_remarks`, `asm_diff`, `asm_diff_timeout`, `crash_capture`. |
| `[wrapper] drop_flags` | Flags removed from every compile. |
| `[results_repo]` | Optional git repo that gets the results after every test. |
| `[env]` | Extra environment variables for PTS and the builds. |
| `[[variant]]` | A compiler: `name`, `llvm_path`, `flags`, `label`, `color`, `inline_replay_from`. The first one is the baseline. |
| `[host.<name>]` | Overrides for the machine with that short hostname. |

`[host.<name>]` lets one config serve several machines, where usually only
paths and core counts differ. Variants are overridden by name, with
`[host.<name>.variant.<variant>]`.

## Commands

All commands that take a config also take:

- `--only TEST...`: only these tests (`z3` or `local/z3`).
- `--variant NAME...`: only these variants.
- `--opt LEVEL...`: only these opt levels.
- `-v`: stream PTS output to the terminal. It always goes to a log file.
- `--force-unsupported`: also build tests whose `SupportedPlatforms` doesn't
  list this OS.
- `--no-audit`: skip the check for objects our clang didn't build.

### `doctor`

Checks the setup before a long run: `php`, PTS, the test profiles link,
every variant's `clang` and `clang++` (a half-rebuilt LLVM fails here, not
mid-run), the LLVM tools, every test, and the plotting libraries.

### `install`

Builds every (test, variant, opt level) once. It doesn't benchmark anything
and doesn't touch the results repo. It keeps going after a failure, and ends
with one status per build:

| Status | Meaning |
| --- | --- |
| `ok` | Built, and every object came from our clang. |
| `build-failed` | The install script failed. See the log it prints. |
| `crashed` | clang crashed. A reproducer is in `crashes/`. |
| `no-compiles` | The script "succeeded" without compiling anything. |
| `foreign-objects` | Built, but some objects weren't built by our clang. |
| `unsupported` | Skipped: the test doesn't list this OS. |

### `run`

For each test and opt level, and for each variant:

1. Build the test `install_rounds` times.
2. Measure object and function sizes.
3. Run the benchmark.

Then it compares each variant's code with the baseline's, copies the PTS
results, regenerates the report and, if configured, commits to the results
repo.

Options: `-p/--prepare` runs `prepare on` first, `--no-report` skips the
plots, `--no-repo` ignores the results repo, `--no-push` commits without
pushing.

### `report`

Regenerates `csv/<opt>/`, `plots/<opt>/` and `README.md` from what's on
disk. `--figure paper` also renders the combined paper figure
(`plots.pdf`, `alive.pdf`, `asm-plots.pdf`). `--results DIR` reads another
dir, including a results repo written by the old `run-all.sh`.

### `prepare on|off`

On Linux, turns off turbo boost, SMT and ASLR, and fixes the CPU frequency
(`prepare-benchmark-env.sh`, needs sudo). On macOS there is no equivalent,
so it only prints a warning.

## How the compiler is swapped in

PTS builds each test with its own `install.sh`. We put a directory of
symlinks first on `PATH`: `cc`, `gcc`, `clang`, `c++`, `g++`, `clang++`,
`nasm` and `yasm`, all pointing to `toolchain/wrapper.py`. `CC` and `CXX`
point there too. So a build file that hardcodes `gcc` still gets our clang.

For every compile, the wrapper:

1. drops the flags in `drop_flags`,
2. replaces every `-O<n>` with the current opt level, and adds it if a
   compile has none,
3. appends the variant's `flags`,
4. runs the variant's clang and records wall time, peak memory and the
   files it wrote.

After each install, an audit lists the object files that no wrapper wrote,
e.g. from a build file calling `/usr/bin/cc` by its full path. Renamed or
copied objects are matched by content.

Calls made under another name than `clang`/`clang++` are reported too. They
point at build files that ignore `$CC`.

## Reducing a crash

When clang crashes during a build, the wrapper keeps a reproducer in
`crashes/<variant>/<test>/<opt>/<n>/`:

| File | Content |
| --- | --- |
| `README` | Signature, crashing function, and the commands below. |
| `stderr.txt` | The assertion or `LLVM ERROR` and the stack dump. |
| `command.sh` | Re-runs the exact crashing command in the right directory. |
| `*.c`, `*.sh` | clang's own reproducer: preprocessed source and script. |
| `input.ll` | The IR before any LLVM pass ran. |
| `interesting.sh` | Test for `llvm-reduce`: exits 0 on the *same* crash. |

`input.ll` comes from re-running the command with
`-S -emit-llvm -Xclang -disable-llvm-passes`. That IR keeps the opt level's
attributes, so compiling it at the same level runs the pipeline that
crashed. The wrapper checks this right away, and records the answer in
`README` and in `crashes/index.tsv`.

```sh
cd crashes/byte/z3/O3/1
# Optional: keep only the function named in the stack dump.
llvm-extract --func=foo input.ll -S -o func.ll
./interesting.sh func.ll && llvm-reduce --test=$PWD/interesting.sh func.ll
```

When the frontend itself crashes, there is no IR. Reduce clang's
preprocessed source with `cvise` or `creduce` instead.

## Output layout

```
output_dir/
  run.json                    clang version of every variant, flags, host, date
  install-summary.tsv         status of every build
  installed-tests/<variant>/<opt>/local/<test>/
  data/<test>/<variant>/<opt>/
    compile.jsonl             one line per compiler call
    object-size.tsv           text bytes per compiled binary
    functions.tsv             size and name of every function
    inline-remarks.txt        with features.inline_remarks
    install-<round>.log, run.log, status.json
  asm-diff/<test>/<opt>/<variant>.json
  test-results/<opt>/<test>/<variant>.xml
  crashes/<variant>/<test>/<opt>/<n>/, crashes/index.tsv
  csv/<opt>/, plots/<opt>/, README.md
```

The results repo gets everything except the installs, the logs, the inline
remarks and the crash reproducers.

## What is measured, exactly

- **Compile time**: the sum of all compiler calls of one build, averaged
  over `install_rounds`.
- **Peak memory**: the largest peak RSS of any single compiler call,
  averaged over the rounds. `results-to-csv.py` divided the largest peak
  of all rounds by the number of rounds instead, so absolute numbers from
  old results repos change; relative ones don't.
- **Object size**: the `text` bytes (code and read-only data) of every
  binary a compile step produced. Executables only count when they were
  compiled straight from sources, so no code is counted twice. On Mach-O,
  this is the sum of the sections in `__TEXT`.
- **Function size**: from `llvm-nm -S` on ELF. Mach-O symbols carry no size,
  so there it is the distance to the next symbol.
- **Asm diff**: per function, `strict` if the instructions differ at all,
  `loose` if the instruction count differs. Operand addresses and offsets
  into other symbols are ignored, since they move when unrelated code
  changes. In linked images, page offsets of data references (`adrp`/`add`
  on arm64, RIP-relative displacements on x86) still show up as strict
  differences.
- **Run time**: whatever the PTS test reports, as % change against the
  baseline.

Only builds that ended `ok` or `foreign-objects` are measured: a build that
failed halfway would otherwise look like a big compile-time win. CMake's
compiler checks (`CompilerId*/a.out`) don't count as program code.

## macOS notes

- Use `-mcpu=native` instead of `-march=native` in `flags`.
- A self-built clang needs the SDK. `bench.py` sets `SDKROOT` from
  `xcrun --show-sdk-path` if it isn't set.
- macOS can't pin a process to a core, so leave `pin_cmd` empty and expect
  noisier run times than on a prepared Linux machine.

## Migrating from `run-all.sh`

| Before | Now |
| --- | --- |
| `config/base.json`, `config/byte.json` | One TOML with two `[[variant]]` tables. |
| Eight positional arguments | `[paths]`, `tests`, `output_dir`, `[results_repo]` in the config. |
| `OPT_FLAG` per config, `"O3"` hardcoded for the plots | `opt_levels`. |
| `-i/--install-only` | `bench.py install`. |
| `-r/--follow-inline-remarks` (only for `byte`) | `inline_replay_from = "base"` on any variant. |
| `-p/--prepare` | `bench.py run -p`, or `bench.py prepare on`. |
| `run.sh` | `bench.py run` with one variant. |
| `results-to-csv.py` | `bench.py report`. |
| `toolchain/clang`, `toolchain/clang++` | `toolchain/wrapper.py`. |

## Test information

`get-test-info.py` lists the version and description of the tests in a
profiles file, as markdown or CSV:

```sh
python3 get-test-info.py /path/to/test-profiles profiles.txt --output-format markdown
```
