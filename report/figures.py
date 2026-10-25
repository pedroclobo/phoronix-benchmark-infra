"""Turn extracted results into CSVs, figures and the results README."""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.gridspec import GridSpec

from . import plot
from .extract import Results

# name -> (title, relative label, absolute label, unit divisor, log scale)
SCALAR_METRICS = {
    "compile-time": ("Compilation Time", "Compile Time (%)",
                     "Compile Time (sec)", 1000, True),
    "memory-usage": ("Memory Usage", "Peak Memory Usage (%)",
                     "Peak Memory Usage (MB)", 1024, False),
    "object-size": ("Object Size", "Binary Size (%)", "Binary Size (kB)",
                    1024, True),
    "instruction-count": ("IR Instruction Count", "IR Instruction Count (%)",
                          "IR Instruction Count", 1, True),
    "alive": ("Alive2 Verification Time",
              "Alive2 Optimization Verification Time (%)",
              "Alive2 Optimization Verification Time (hours)", 3600, False),
}


def scalar(results: Results, name: str) -> pd.DataFrame:
    return {
        "compile-time": results.compile_time,
        "memory-usage": results.memory_usage,
        "object-size": results.object_size,
        "instruction-count": results.instruction_count,
        "alive": results.alive,
    }[name]()


def runtime_pct(results: Results, styles: list[dict]) -> pd.DataFrame:
    """% change of each variant vs baseline, averaged over a test's results.

    Positive means slower. For higher-is-better results (Mflops) the change
    is measured relative to the variant, as before:
    (base - variant) / variant.
    """
    rt = results.runtime().df
    if rt.empty:
        return pd.DataFrame()
    base = styles[0]["name"]
    w = rt.pivot_table(index=["test", "description", "higher"],
                       columns="variant", values="value").reset_index()
    if base not in w.columns:
        return pd.DataFrame()
    out = {}
    for s in styles[1:]:
        n = s["name"]
        if n not in w.columns:
            continue
        hib = (w[base] - w[n]) / w[n] * 100
        lib = (w[n] - w[base]) / w[base] * 100
        out[n] = hib.where(w["higher"], lib)
    pct = pd.DataFrame(out)
    pct["test"] = w["test"]
    return pct.groupby("test").mean().dropna().sort_index(ascending=False)


def save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def single(draw, rows: int, path: Path, styles, relative_only: bool) -> None:
    """One metric, one panel, legend on top."""
    fig, ax = plt.subplots(figsize=(7, 1 + 0.25 * rows))
    draw(ax)
    plot.legend(fig, styles, relative_only)
    plt.tight_layout(rect=[0, 0, 1, 0.93])
    save(fig, path)


def default_figures(results: Results, styles: list[dict], csv_dir: Path,
                    plot_dir: Path) -> list[tuple[str, str]]:
    """CSVs plus one relative plot per metric. Returns (title, file) pairs
    for the README."""
    base = styles[0]["name"]
    written = []
    csv_dir.mkdir(parents=True, exist_ok=True)

    for name, (title, rel_label, _, _, _) in SCALAR_METRICS.items():
        df = scalar(results, name)
        if df.empty:
            continue
        w = plot.wide(df, styles)
        w.sort_index().to_csv(csv_dir / f"{name}.csv", sep=";")
        if base not in w.columns or len(w.columns) < 2 or w.empty:
            continue
        pct = plot.percent_change(w, base)
        single(lambda ax: plot.relative(pct, ax, rel_label, styles),
               len(pct), plot_dir / f"{name}.svg", styles, True)
        written.append((title, f"{name}.svg"))

    pct = runtime_pct(results, styles)
    if not pct.empty:
        results.runtime().df.to_csv(csv_dir / "runtime.csv", sep=";",
                                    index=False)
        single(lambda ax: plot.relative(pct, ax, "Run-time Performance (%)",
                                        styles),
               len(pct), plot_dir / "runtime.svg", styles, True)
        written.append(("Runtime", "runtime.svg"))

    funcs = results.function_sizes()
    diff = results.asm_diff().df
    if diff["variant"].isna().any() and len(styles) > 1:
        diff["variant"] = diff["variant"].fillna(styles[1]["name"])
    if not funcs.empty:
        funcs.to_csv(csv_dir / "asm-size.csv", sep=";", index=False)
        plot_dir.mkdir(parents=True, exist_ok=True)
        plot.asm_histograms(funcs, diff, styles, plot_dir / "asm-size.svg")
        if (plot_dir / "asm-size.svg").is_file():
            written.append(("ASM Size", "asm-size.svg"))
    if not diff.empty:
        diff.to_csv(csv_dir / "asm-diff.csv", sep=";", index=False)
        diff = diff.assign(value=diff["loose"] / diff["functions"] * 100)
        w = diff.pivot_table(index="test", columns="variant", values="value")
        w = w.sort_index(ascending=False)
        single(lambda ax: asm_diff_bars(w, ax, styles), len(w),
               plot_dir / "asm-diff.svg", styles, False)
        written.append(("ASM Diff", "asm-diff.svg"))
    return written


def asm_diff_bars(w: pd.DataFrame, ax, styles: list[dict]) -> None:
    """% of the baseline's functions whose instruction count changed."""
    color_of = {s["name"]: s["color"] for s in styles}
    ax.set_facecolor(plot.BACKGROUND)
    w.plot(kind="barh", ax=ax, width=0.8, legend=False,
           color=[color_of.get(c, "gray") for c in w.columns])
    ax.set(ylabel=None)
    ax.set_xlabel("Functions with a different instruction count (%)",
                  fontsize=plot.PLOT_FONT_SIZE, color=plot.BLACK)
    ax.xaxis.set_label_position("top")
    plot.yticks(ax, list(w.index), True)


def paper_figures(results: Results, styles: list[dict],
                  plot_dir: Path) -> None:
    """The combined figure from the paper: five metrics on a 2x12 grid,
    the Alive2 strip and the asm-size histograms, as PDFs."""
    base = styles[0]["name"]
    fig = plt.figure(figsize=(12, 10))
    gs = GridSpec(2, 12, figure=fig, height_ratios=[1, 1], hspace=0.15,
                  wspace=0.1, left=0.08, right=0.98, top=0.94, bottom=0.05)
    slots = {
        "compile-time": gs[0, 0:4],
        "runtime": gs[0, 4:8],
        "memory-usage": gs[0, 8:12],
        "object-size": gs[1, 2:6],
        "instruction-count": gs[1, 6:10],
    }
    for name, slot in slots.items():
        ax = fig.add_subplot(slot)
        first = name in ("compile-time", "object-size")
        if name == "runtime":
            pct = runtime_pct(results, styles)
            if not pct.empty:
                plot.relative(pct, ax, "Run-time Performance (%)", styles,
                              show_tests=first)
            continue
        _, _, abs_label, divisor, log = SCALAR_METRICS[name]
        w = plot.wide(scalar(results, name), styles)
        if base in w.columns and not w.empty:
            plot.absolute(w / divisor, ax, abs_label, styles, log=log,
                          show_tests=first)
        else:
            ax.set_visible(False)
    plot.legend(fig, styles, False)
    save(fig, plot_dir / "plots.pdf")

    alive = plot.wide(scalar(results, "alive"), styles)
    if base in alive.columns and not alive.empty:
        fig, ax = plt.subplots(figsize=(8, 2))
        plot.absolute(alive / 3600, ax, SCALAR_METRICS["alive"][2], styles)
        plot.legend(fig, styles, False)
        plt.tight_layout(rect=[0, 0, 1, 0.88])
        save(fig, plot_dir / "alive.pdf")

    funcs = results.function_sizes()
    if not funcs.empty:
        plot.asm_histograms(funcs, results.asm_diff().df, styles,
                            plot_dir / "asm-plots.pdf")


def readme(root: Path, title: str, inline_replay: bool,
           sections: dict[str, list[tuple[str, str]]]) -> None:
    """The results README: one section per opt level, one plot per metric."""
    lines = [f"# {title}", ""]
    lines.append(f"Follow inline remarks: {'[x]' if inline_replay else '[ ]'}")
    lines.append("")
    for opt, plots in sections.items():
        if len(sections) > 1:
            lines += [f"## -{opt}", ""]
        for name, file in plots:
            lines += [f"{'###' if len(sections) > 1 else '##'} {name}",
                      f"![{name}](plots/{opt}/{file})", ""]
    (root / "README.md").write_text("\n".join(lines))
