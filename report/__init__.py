"""`bench.py report`: CSVs, plots and the results README.

This replaces results-to-csv.py. It needs matplotlib, numpy and pandas
(`pip install -r requirements.txt`), unlike the rest of bench.py.
"""

import socket
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # files only, never a window

from . import figures, plot  # noqa: E402
from .extract import Results  # noqa: E402


def build(cfg, layout, figure: str = "default",
          results_root: Path | None = None) -> None:
    """Write csv/<opt>/, plots/<opt>/ and README.md under the results root.

    `results_root` defaults to the config's output_dir. It can also point at
    a results repo written by the old run-all.sh.
    """
    root = results_root or layout.root
    styles = plot.styles_from(cfg.variants)
    sections = {}
    legacy = False
    for opt in cfg.opt_levels:
        results = Results.load(root, opt)
        legacy = type(results) is not Results
        o = opt.lstrip("-")
        sections[o] = figures.default_figures(
            results, styles, root / "csv" / o, root / "plots" / o)
        if figure == "paper":
            figures.paper_figures(results, styles, root / "plots" / o)
        print(f"report: wrote {root / 'plots' / o}")
    # An old results repo keeps its own README.
    if not legacy:
        title = (f"{datetime.now():%d %B %Y - %H:%M} @ "
                 f"{socket.gethostname()}")
        figures.readme(root, title,
                       any(v.inline_replay_from for v in cfg.variants),
                       sections)
