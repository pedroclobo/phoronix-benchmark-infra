"""Read raw results into DataFrames.

Every scalar metric comes back in the same long format, one row per
(test, variant):

    test | variant | value

`Results.load` picks a reader based on what is on disk:

- the layout `bench.py` writes (see pbench/layout.py), or
- the layout of the old run-all.sh results repos, so their figures can still
  be regenerated.
"""

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

COLUMNS = ["test", "variant", "value"]


def frame(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["value"] = pd.to_numeric(df["value"])
    return df.sort_values(["test", "variant"], ignore_index=True)


@dataclass
class Runtime:
    """PTS results: one row per (test, result, variant).

    A test can report several results (e.g. one per input size). `higher`
    is True when a higher value is better (`HIB` in PTS).
    """

    df: pd.DataFrame  # test | description | higher | variant | value


@dataclass
class AsmDiff:
    """Per (test, variant): how many functions changed against the baseline."""

    df: pd.DataFrame  # test | variant | functions | strict | loose | timed_out


class Results:
    """All metrics of one results dir for one opt level."""

    def __init__(self, root: Path, opt: str):
        self.root = root
        self.opt = opt.lstrip("-")

    @staticmethod
    def load(root: Path, opt: str) -> "Results":
        legacy = (root / "compile-time").is_dir() and not (root / "data").is_dir()
        return (LegacyResults if legacy else Results)(root, opt)

    # --- bench.py layout ----------------------------------------------------

    def _runs(self):
        """Yield (test, variant, dir) for every data dir of this opt whose
        build succeeded. A failed or crashed build compiled only part of the
        program, so its numbers would look like a big improvement."""
        for d in sorted((self.root / "data").glob(f"*/*/{self.opt}")):
            status = d / "status.json"
            if status.is_file() and json.loads(status.read_text()).get(
                    "status") not in ("ok", "foreign-objects"):
                continue
            yield d.parent.parent.name, d.parent.name, d

    def _compiles(self, d: Path) -> pd.DataFrame:
        f = d / "compile.jsonl"
        if not f.is_file():
            return pd.DataFrame(columns=["round", "ms", "rss_kb"])
        recs = [json.loads(l) for l in f.read_text().splitlines() if l]
        recs = [r for r in recs if r["kind"] == "cc"]
        return pd.DataFrame(recs, columns=["round", "ms", "rss_kb"])

    def compile_time(self) -> pd.DataFrame:
        """Total compile time of a build in ms, averaged over the rounds."""
        rows = []
        for test, variant, d in self._runs():
            c = self._compiles(d)
            if len(c):
                rows.append((test, variant, c.groupby("round")["ms"].sum().mean()))
        return frame(rows)

    def memory_usage(self) -> pd.DataFrame:
        """Peak memory of any single compiler call in KiB, averaged over the
        rounds."""
        rows = []
        for test, variant, d in self._runs():
            c = self._compiles(d)
            if len(c):
                rows.append((test, variant,
                             c.groupby("round")["rss_kb"].max().mean()))
        return frame(rows)

    def object_size(self) -> pd.DataFrame:
        """Sum of `text` bytes over all compiled binaries."""
        rows = []
        for test, variant, d in self._runs():
            f = d / "object-size.tsv"
            if f.is_file():
                total = sum(int(l.split("\t", 1)[0])
                            for l in f.read_text().splitlines() if l)
                rows.append((test, variant, total))
        return frame(rows)

    def function_sizes(self) -> pd.DataFrame:
        """test | variant | function | size"""
        rows = []
        for test, variant, d in self._runs():
            f = d / "functions.tsv"
            if not f.is_file():
                continue
            for line in f.read_text().splitlines():
                size, name = line.split("\t", 1)
                rows.append((test, variant, name, int(size)))
        return pd.DataFrame(rows, columns=["test", "variant", "function", "size"])

    def asm_diff(self) -> AsmDiff:
        rows = []
        for f in sorted((self.root / "asm-diff").glob(f"*/{self.opt}/*.json")):
            d = json.loads(f.read_text())
            rows.append((f.parent.parent.name, f.stem, d["functions"],
                         len(d["strict"]), len(d["loose"]), d["timed_out"]))
        return AsmDiff(pd.DataFrame(rows, columns=[
            "test", "variant", "functions", "strict", "loose", "timed_out"]))

    def runtime(self) -> Runtime:
        files = sorted((self.root / "test-results" / self.opt).glob("*/*.xml"))
        return Runtime(parse_composites(files))

    def instruction_count(self) -> pd.DataFrame:
        return self._external("instr-count", "instruction-count")

    def alive(self) -> pd.DataFrame:
        return self._external("alive", "alive")

    def _external(self, raw_dir: str, csv_name: str) -> pd.DataFrame:
        """Metrics that bench.py doesn't produce. They come from the old raw
        dirs if present, else from a hand-made `csv/<name>.csv`."""
        legacy = LegacyResults(self.root, self.opt)
        if (self.root / raw_dir).is_dir():
            return getattr(legacy, f"_{raw_dir.replace('-', '_')}")()
        return read_wide_csv(self.root / "csv" / f"{csv_name}.csv")


class LegacyResults(Results):
    """Reader for results repos written by the old run-all.sh.

    Layout: <metric>/<test>/<profile>/<opt>[...], with `<opt>` without dash.
    """

    def _dirs(self, metric: str):
        base = self.root / metric
        if not base.is_dir():
            return
        for test in sorted(p for p in base.iterdir() if p.is_dir()):
            for variant in sorted(p for p in test.iterdir() if p.is_dir()):
                yield test.name, variant.name, variant

    def compile_time(self) -> pd.DataFrame:
        # <round>.txt holds one "command<TAB>ms" line per compiler call.
        rows = []
        for test, variant, d in self._dirs("compile-time"):
            files = list((d / self.opt).glob("*.txt"))
            if files:
                total = sum(int(l.rsplit("\t", 1)[1]) for f in files
                            for l in f.read_text().splitlines() if "\t" in l)
                rows.append((test, variant, total / len(files)))
        return frame(rows)

    def memory_usage(self) -> pd.DataFrame:
        # <round>.txt holds one peak-KiB number per compiler call. The old
        # script divided the overall max by the number of rounds; this takes
        # the mean of the per-round maxima instead.
        rows = []
        for test, variant, d in self._dirs("memory-usage"):
            peaks = []
            for f in (d / self.opt).glob("*.txt"):
                nums = [int(l) for l in f.read_text().split() if l.isdigit()]
                if nums:
                    peaks.append(max(nums))
            if peaks:
                rows.append((test, variant, sum(peaks) / len(peaks)))
        return frame(rows)

    def object_size(self) -> pd.DataFrame:
        # Output of GNU `size`: a header line, then text/data/bss/... per file.
        rows = []
        for test, variant, d in self._dirs("object-size"):
            f = d / f"{self.opt}.txt"
            if not f.is_file():
                continue
            total = 0
            for line in f.read_text().splitlines():
                first = line.split("\t")[0].strip()
                if first.isdigit():
                    total += int(first)
            rows.append((test, variant, total))
        return frame(rows)

    def function_sizes(self) -> pd.DataFrame:
        rows = []
        for test, variant, d in self._dirs("asm-diff"):
            f = d / self.opt / "sizes.txt"
            if not f.is_file():
                continue
            for line in f.read_text().splitlines():
                size, name = line.split(maxsplit=1)
                rows.append((test, variant, name, int(size)))
        return pd.DataFrame(rows, columns=["test", "variant", "function", "size"])

    def asm_diff(self) -> AsmDiff:
        # The old diff only compared two configs, so the counts belong to the
        # non-baseline one. Its name is filled in by the caller.
        rows = []
        base = self.root / "asm-diff"
        for test in sorted(p for p in base.iterdir() if p.is_dir()) \
                if base.is_dir() else []:
            d = test / self.opt

            def count(name: str) -> int:
                f = d / name
                return len(f.read_text().splitlines()) if f.is_file() else 0

            if (d / "all.txt").is_file():
                timeout = d / "timeout.txt"
                rows.append((test.name, None, count("all.txt"),
                             count("diff.txt"), count("diff_loose.txt"),
                             timeout.is_file()
                             and timeout.read_text().strip() == "y"))
        return AsmDiff(pd.DataFrame(rows, columns=[
            "test", "variant", "functions", "strict", "loose", "timed_out"]))

    def runtime(self) -> Runtime:
        files = sorted((self.root / "test-results").glob(
            f"*/{self.opt}/composite.xml"))
        return Runtime(parse_composites(files))

    def _instr_count(self) -> pd.DataFrame:
        # <opt>.txt holds "function;count" lines.
        rows = []
        for test, variant, d in self._dirs("instr-count"):
            f = d / f"{self.opt}.txt"
            if f.is_file():
                rows.append((test, variant, sum(
                    int(l.split(";")[1]) for l in f.read_text().splitlines()
                    if ";" in l)))
        return frame(rows)

    def _alive(self) -> pd.DataFrame:
        # <opt>/*.txt hold "...<TAB>seconds" lines; averaged over files.
        rows = []
        for test, variant, d in self._dirs("alive"):
            files = list((d / self.opt).glob("*.txt"))
            if files:
                total = sum(int(l.rsplit("\t", 1)[1]) for f in files
                            for l in f.read_text().splitlines() if "\t" in l)
                rows.append((test, variant, total / len(files)))
        return frame(rows)


def parse_composites(files: list[Path]) -> pd.DataFrame:
    """PTS composite.xml files -> test | description | higher | variant | value"""
    rows = []
    for f in files:
        root = ET.parse(f).getroot()
        for result in root.findall(".//Result"):
            # `local/openssl-3.0.1` -> `openssl-3.0.1`, the data dir name.
            test = (result.findtext("Identifier") or "").split("/")[-1]
            desc = result.findtext("Description") or ""
            higher = result.findtext("Proportion") == "HIB"
            for entry in result.findall(".//Data/Entry"):
                value = entry.findtext("Value")
                if value:
                    rows.append((test, desc, higher,
                                 entry.findtext("Identifier"), float(value)))
    return pd.DataFrame(rows, columns=["test", "description", "higher",
                                       "variant", "value"])


def read_wide_csv(path: Path) -> pd.DataFrame:
    """`Test;<variant>;<variant>...` as written by the old merge_results."""
    if not path.is_file():
        return frame([])
    wide = pd.read_csv(path, sep=";")
    long = wide.melt(id_vars=wide.columns[0], var_name="variant",
                     value_name="value")
    long = long.rename(columns={wide.columns[0]: "test"})
    return frame(list(long[COLUMNS].itertuples(index=False, name=None)))
