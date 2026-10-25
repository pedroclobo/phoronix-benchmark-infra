"""Where everything lives inside `output_dir`.

    output_dir/
      run.json                              manifest of the last run
      install-summary.tsv                   status of every install
      installed-tests/<variant>/<opt>/local/<test>/   PTS install dirs
      data/<test>/<variant>/<opt>/
        compile.jsonl                       one line per compiler call
        inline-remarks.txt                  if features.inline_remarks
        object-size.tsv                     text bytes per compiled binary
        functions.tsv                       size and name of each function
        install-<round>.log                 PTS output
        status.json                         result of the last install
      asm-diff/<test>/<opt>/<variant>.json  functions that differ from baseline
      test-results/<opt>/composite.xml      PTS runtime results
      crashes/<variant>/<test>/<opt>/<n>/   crash reproducers
      crashes/index.tsv                     every crash, one per line
      csv/, plots/, README.md               written by `bench.py report`

`<opt>` is the opt level without its dash, e.g. `O3`. `<test>` is the test
name without its `local/` prefix.
"""

from pathlib import Path


def opt_name(opt: str) -> str:
    return opt.lstrip("-")


def test_name(test: str) -> str:
    return test.split("/")[-1]


class Layout:
    def __init__(self, root: Path):
        self.root = root

    def install_root(self, variant: str, opt: str) -> Path:
        """Value of PTS_TEST_INSTALL_ROOT_PATH. PTS appends `local/<test>`."""
        return self.root / "installed-tests" / variant / opt_name(opt)

    def install_dir(self, test: str, variant: str, opt: str) -> Path:
        return self.install_root(variant, opt) / test

    def data(self, test: str, variant: str, opt: str) -> Path:
        return self.root / "data" / test_name(test) / variant / opt_name(opt)

    def crashes(self, test: str, variant: str, opt: str) -> Path:
        return (self.root / "crashes" / variant / test_name(test)
                / opt_name(opt))

    def asm_diff(self, test: str, opt: str) -> Path:
        return self.root / "asm-diff" / test_name(test) / opt_name(opt)

    def test_results(self, opt: str) -> Path:
        return self.root / "test-results" / opt_name(opt)

    @property
    def shims(self) -> Path:
        return self.root / "shims"

    @property
    def manifest(self) -> Path:
        return self.root / "run.json"

    @property
    def summary(self) -> Path:
        return self.root / "install-summary.tsv"
