"""Plot primitives shared by all metrics.

`absolute` and `relative` draw one horizontal bar group per test. They take a
wide DataFrame: one row per test, one column per variant, with the baseline
first. `asm_histograms` draws the per-test function-size figure.
"""

import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ANNOTATION_FONT_SIZE = 8
PLOT_FONT_SIZE = 10

BACKGROUND = "#F6F8FA"
BLACK = "#24292E"
GREEN = "#22863A"
RED = "#D73A49"
BRIGHTGREEN = "#28A745"
BRIGHTRED = "#CB2431"
BRIGHTYELLOW = "#DBAB09"

# Fallback colors for variants without `color` in the config.
PALETTE = ["#E69F00", "#0077BB", "#CC3311", "#009988", "#EE7733", "#33BBEE"]

# Display names for tests whose profile name carries a version.
TEST_ALIASES = {"openssl-3.0.1": "openssl"}

plt.rcParams["image.composite_image"] = False  # avoids unwanted blending


def styles_from(variants) -> list[dict]:
    """[{name, label, color}] for each configured variant, baseline first."""
    return [{"name": v.name, "label": v.label or v.name,
             "color": v.color or PALETTE[i % len(PALETTE)]}
            for i, v in enumerate(variants)]


def wide(df: pd.DataFrame, styles: list[dict]) -> pd.DataFrame:
    """Long (test, variant, value) -> one column per variant.

    Tests missing any variant are dropped, since they can't be compared.
    Rows are sorted so the first test alphabetically ends up on top.
    """
    names = [s["name"] for s in styles]
    w = df.pivot_table(index="test", columns="variant", values="value")
    w = w.reindex(columns=[n for n in names if n in w.columns]).dropna()
    return w.sort_index(ascending=False)


def percent_change(w: pd.DataFrame, base: str) -> pd.DataFrame:
    """(variant - base) / base, in %. Positive means bigger or slower."""
    return w.drop(columns=[base]).sub(w[base], axis=0).div(w[base], axis=0) * 100


def yticks(ax, tests, show: bool) -> None:
    ax.set_yticks(range(len(tests)))
    ax.set_yticklabels([TEST_ALIASES.get(t, t) for t in tests] if show
                       else [])
    if not show:
        ax.set_yticks([])


def absolute(w: pd.DataFrame, ax, xlabel: str, styles: list[dict],
             log: bool = False, show_tests: bool = True) -> None:
    """Grouped bars of raw values, annotated with the % change vs baseline."""
    ax.set_facecolor(BACKGROUND)
    names = list(w.columns)
    colors = [next(s["color"] for s in styles if s["name"] == n) for n in names]
    w.plot(kind="barh", ax=ax, color=colors, width=0.8, legend=False)
    for container in ax.containers:
        for bar in container.patches:
            bar.set_edgecolor("black")
            bar.set_linewidth(0.5)
    ax.set(ylabel=None)
    ax.set_xlabel(xlabel, fontsize=PLOT_FONT_SIZE, color=BLACK)
    ax.xaxis.set_label_position("top")
    if log:
        ax.set_xscale("log")

    # Leave room on the right for the annotations. On a log scale, start
    # below the smallest bar so every bar stays visible.
    top, bottom = w.to_numpy().max(), w.to_numpy().min()
    ax.set_xlim(bottom / 2 if log else 0, top * 1.5 if log else top * 1.1)
    ax.set_ylim(-0.75, len(w) - 0.25)
    yticks(ax, list(w.index), show_tests)

    base = names[0]
    x_min, x_max = ax.get_xlim()
    for i, test in enumerate(w.index):
        for other in names[1:]:
            b, o = w.loc[test, base], w.loc[test, other]
            pct = (o - b) / b * 100
            color = (BRIGHTRED if round(pct, 2) > 0 else
                     BRIGHTGREEN if round(pct, 2) < 0 else BRIGHTYELLOW)
            x = (1.1 * max(b, o) if log else
                 max(0.05 * (x_max - x_min), max(b, o) + 0.02 * (x_max - x_min)))
            ax.text(x, i - 0.025, f"{pct:.2f}%", ha="left", color=color,
                    fontsize=ANNOTATION_FONT_SIZE, fontweight="bold")


def relative(pct: pd.DataFrame, ax, xlabel: str, styles: list[dict],
             show_tests: bool = True) -> None:
    """Bars of % change vs baseline, one row per test.

    Bars point right for improvements (negative change) and left for
    regressions. With a single non-baseline variant, bars are green or red;
    with several, each variant keeps its color and the largest bar is drawn
    first so smaller ones stay visible on top.
    """
    ax.set_facecolor(BACKGROUND)
    names = list(pct.columns)
    color_of = {s["name"]: s["color"] for s in styles}
    single = len(names) == 1

    lo, hi = pct.to_numpy().min(), pct.to_numpy().max()
    ax.set_xlim(min(-1.5, -hi * 1.2), max(1.5, -lo * 1.2))

    for row, test in enumerate(pct.index):
        values = sorted(((abs(pct.loc[test, n]), n) for n in names),
                        reverse=True)
        for _, n in values:
            v = pct.loc[test, n]
            color = (GREEN if v < 0 else RED) if single else color_of[n]
            ax.barh(y=row, width=-v, height=0.8, color=color,
                    edgecolor="black", linewidth=0.3)

    ax.set_ylim(-0.75, len(pct) - 0.25)
    ax.set(ylabel=None)
    ax.set_xlabel(xlabel, fontsize=PLOT_FONT_SIZE, color=BLACK)
    ax.xaxis.set_label_position("top")
    for y in range(len(pct)):
        ax.axhline(y, color="gray", linestyle="solid", linewidth=0.5, alpha=0.3)
    ax.axvline(0, color="black", linestyle="solid", linewidth=0.75, alpha=0.6)
    yticks(ax, list(pct.index), show_tests)


def legend(fig, styles: list[dict], relative_only: bool) -> None:
    """Variant legend across the top. Relative plots don't show the baseline
    and, with one other variant, use green/red for better/worse."""
    shown = styles[1:] if relative_only else styles
    handles = [plt.Rectangle((0, 0), 1, 1, fc=s["color"], edgecolor=BLACK)
               for s in shown]
    labels = [s["label"] for s in shown]
    if relative_only and len(styles) == 2:
        handles = [plt.Rectangle((0, 0), 1, 1, fc=c, edgecolor=BLACK)
                   for c in (GREEN, RED)]
        labels = [f"{styles[1]['label']}: better", f"{styles[1]['label']}: worse"]
    fig.legend(handles=handles, labels=labels, loc="upper center",
               ncol=len(handles), fontsize=PLOT_FONT_SIZE, frameon=True,
               framealpha=1, bbox_to_anchor=(0.5, 1.0))


def asm_histograms(funcs: pd.DataFrame, diff: pd.DataFrame,
                   styles: list[dict], path) -> None:
    """Two panels per test: function sizes, and size change per function.

    Only functions present in every variant are compared. The left panel
    overlays each variant's size histogram (log scale). The right one shows
    `size(variant) - size(baseline)` for each function.
    """
    names = [s["name"] for s in styles if s["name"] in set(funcs["variant"])]
    if len(names) < 2:
        return
    base = names[0]
    color_of = {s["name"]: s["color"] for s in styles}
    label_of = {s["name"]: s["label"] for s in styles}

    tests = []
    for test, g in funcs.groupby("test"):
        sizes = g.pivot_table(index="function", columns="variant",
                              values="size", aggfunc="max")
        sizes = sizes.reindex(columns=names).dropna()
        if len(sizes):
            tests.append((test, sizes))
    if not tests:
        return

    n_cols = 4
    n_rows = math.ceil(len(tests) / 2)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(14, 1.75 * n_rows),
                             squeeze=False)
    axes = axes.flatten()
    for i, (test, sizes) in enumerate(tests):
        ax_size, ax_diff = axes[2 * i], axes[2 * i + 1]
        for ax in (ax_size, ax_diff):
            ax.set_facecolor(BACKGROUND)

        total = int(sizes[names[1]].sum() - sizes[base].sum())
        title = TEST_ALIASES.get(test, test)
        ax_size.set_title(f"{title}: {total:+,d} bytes" if len(names) == 2
                          else title, fontsize=PLOT_FONT_SIZE)
        lo, hi = max(1, sizes.to_numpy().min()), max(2, sizes.to_numpy().max())
        bins = np.logspace(np.log10(lo), np.log10(hi), 70)
        for n in names:
            ax_size.hist(sizes[n], bins=bins, alpha=0.6, color=color_of[n])
        ax_size.set_xscale("log")

        changed = diff[diff["test"] == test]
        summary = test
        if len(names) == 2 and len(changed):
            r = changed.iloc[0]
            pct = r["loose"] / r["functions"] * 100 if r["functions"] else 0
            summary = (f"{title}: {r['loose']:,d}/{r['functions']:,d} "
                       f"({pct:.1f}%)" + (" timed out" if r["timed_out"] else ""))
        ax_diff.set_title(summary, fontsize=PLOT_FONT_SIZE)
        deltas = {n: sizes[n] - sizes[base] for n in names[1:]}
        span = max(1, max(d.abs().max() for d in deltas.values()))
        dbins = np.linspace(-span, span, 151)
        for n, d in deltas.items():
            ax_diff.hist(d, bins=dbins, alpha=0.6, color=color_of[n])
        ax_diff.set_yscale("log")
        ax_diff.set_xlim(-span * 1.1, span * 1.1)
        ax_size.grid(True, which="both", axis="y", linestyle="dotted",
                     color="#8B949E", alpha=0.5)
        ax_diff.grid(True, which="both", axis="x", linestyle="dotted",
                     color="#8B949E", alpha=0.5)

    for ax in axes[2 * len(tests):]:
        ax.axis("off")
    for i in range(len(axes) - n_cols, len(axes)):
        if axes[i].axison:
            axes[i].set_xlabel("Function Size (bytes)" if i % 2 == 0
                               else "Size Difference (bytes)",
                               fontsize=PLOT_FONT_SIZE, color=BLACK)

    handles = [plt.Rectangle((0, 0), 1, 1, fc=color_of[n]) for n in names]
    plt.tight_layout()
    # Above the panels, so it never covers a title.
    fig.legend(handles=handles, labels=[label_of[n] for n in names],
               loc="lower center", ncol=len(names), fontsize=PLOT_FONT_SIZE,
               frameon=True, framealpha=1, bbox_to_anchor=(0.5, 1))
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
