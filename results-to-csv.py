import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
import xml.etree.ElementTree as ET
import argparse
import re
import math
from matplotlib.ticker import AutoMinorLocator
import matplotlib.lines as mlines
from matplotlib.gridspec import GridSpec
from matplotlib.colors import LinearSegmentedColormap

plt.rcParams['image.composite_image'] = False  # avoids unwanted blending

ANNOTATION_FONT_SIZE = 8
PLOT_FONT_SIZE = 10
ROW_SIZE = 0.2
PLOT_WIDTH = 7

BACKGROUND = "#F6F8FA"
BLACK = "#24292E"
BLUE = "#0366D6"
BRIGHTBLACK = "#586069"
BRIGHTBLUE = "#2188FF"
BRIGHTCYAN = "#3192AA"
BRIGHTGREEN = "#28A745"
BRIGHTPURPLE = "#8A63D2"
BRIGHTRED = "#CB2431"
BRIGHTWHITE = "#959DA5"
BRIGHTYELLOW = "#DBAB09"
CYAN = "#1B7C83"
GREEN = "#22863A"
PURPLE = "#6F42C1"
RED = "#D73A49"
WHITE = "#6A737D"
YELLOW = "#B08800"
ORANGE = "#F66A0A"

def plot_absolute(df, ax, xlabel, styles, log=False, yticks=True):
    ax.set_facecolor(BACKGROUND)

    num_tests = len(df["Test"])

    profiles = [profile["name"] for profile in styles]
    colors = [profile["color"] for profile in styles]
    df.plot(kind="barh", ax=ax, color=colors, width=0.8)

    for i, container in enumerate(ax.containers):
        for bar in container.patches:
            bar.set_hatch(styles[i]["hatch"])
            bar.set_edgecolor("black")
            bar.set_linewidth(0.5)

    ax.set(ylabel=None)
    ax.set_xlabel(xlabel, fontsize=PLOT_FONT_SIZE, color=BLACK)
    ax.xaxis.set_label_position("top")
    if log:
        ax.set_xscale("log")

    # Prevent annotations from going outside the plot
    max_value = df[profiles].to_numpy().max()
    ax.set_xlim(2 if log else 1, max_value * 1.5 if log else max_value * 1.1)

    ax.set_ylim(-0.75, num_tests - 0.25)

    if yticks:
        ax.set_yticklabels(df["Test"])
    else:
        ax.set_yticks([])

    # Annotate plots with regression percentage
    for i, test in enumerate(df.index):
        i = i - 1
        for j, profile in enumerate(profiles[1::]):
            j = j + 1
            base_value = df.loc[test, "base"]
            other_value = df.loc[test, profile]

            percentage_change = ((other_value - base_value) / base_value) * 100
            if round(percentage_change, 2) == 0.00:
                percentage_change *= percentage_change
            change_text = f"{percentage_change:.2f}%"
            rounded_percentage_change = round(percentage_change, 2)

            x_min, x_max = ax.get_xlim()
            ax.text(
                1.1 * max(base_value, other_value) if log
                else max(
                    0.05 * (x_max - x_min),
                    max(base_value, other_value) + 0.02 * (x_max - x_min),
                ),
                i + 1 - 0.025,
                change_text,
                ha="left",
                color=(
                    BRIGHTRED
                    if rounded_percentage_change > 0
                    else BRIGHTGREEN if rounded_percentage_change < 0 else BRIGHTYELLOW
                ),
                fontsize=ANNOTATION_FONT_SIZE,
                fontweight="bold",
            )

def plot_relative(df, ax, xlabel, styles, yticks=True):
    ax.set_facecolor(BACKGROUND)

    profiles = [profile["name"] for profile in styles]
    num_tests = len(df["Test"].unique())
    num_profiles = len(profiles)

    if num_profiles == 2:
        colors = [
            GREEN if percentage < 0 else RED
            for percentage in df[profiles[-1]]
        ]
    else:
        colors = [profile["color"] for profile in styles[1::]]

    # Prevent annotations from going outside the plot
    min_percentage = df[profiles[1::]].to_numpy().min()
    max_percentage = df[profiles[1::]].to_numpy().max()
    ax.set_xlim(min(-1.5, -max_percentage * 1.2), max(1.5, -min_percentage * 1.2))

    for test_idx in range(len(df)):
        test_bars = []
        for i, profile in enumerate(profiles[1:]):
            abs_val = abs(df[profile].iloc[test_idx])
            test_bars.append((i, profile, abs_val))

        # Sort by absolute value, descending (largest first)
        test_bars.sort(key=lambda x: x[2], reverse=True)

        # Draw bars for this test in sorted order
        for original_idx, profile, _ in test_bars:
            value = -df[profile].iloc[test_idx]
            bar_height = 0.8

            color = (styles[original_idx + 1]["color"]
                    if num_profiles > 2
                    else (GREEN if df[profile].iloc[test_idx] < 0 else RED))

            ax.barh(
                y=test_idx,
                width=value,
                height=bar_height,
                color=color,
                edgecolor="black",
                hatch=styles[original_idx + 1]["hatch"] if num_profiles > 2 else None,
                linewidth=0.3,
            )

    # Create legend entries manually since we're not using labels in the loop
    if num_profiles > 2:
        for i, profile in enumerate(profiles[1:]):
            ax.barh([], [], color=styles[i + 1]["color"],
                   hatch=styles[i + 1]["hatch"],
                   edgecolor="black", label=profile)

    ax.set_ylim(-0.75, len(df) - 0.25)

    # # TODO: collection of all bars, sort them by size (by test)
    # # and draw the bars from the bigger ones to the smaller ones
    # bars = []
    #
    # profile_widths = [(i, profile, df[profile].abs().mean())
    #                   for i, profile in enumerate(profiles[1:])]
    # profile_widths.sort(key=lambda x: x[2], reverse=True)
    # print(profile_widths)
    # for original_idx, profile, _ in profile_widths:
    #     values = -df[profile][::-1]
    #     bar_height = 0.8
    #     ax.barh(
    #         y=df.index,
    #         width=values,
    #         height=bar_height,
    #         color=styles[original_idx + 1]["color"]
    #               if num_profiles > 2
    #               else [GREEN if p < 0 else RED for p in df[profiles[-1]]][::-1],
    #         edgecolor="black",
    #         hatch=styles[original_idx + 1]["hatch"] if num_profiles > 2 else None,
    #         label=profile,
    #         linewidth=0.8,
    #     )
    #
    # ax.set_ylim(-0.75, len(df) - 0.25)
    #
    # for i, container in enumerate(ax.containers):
    #     for j, bar in enumerate(container.patches):
    #         percentage = df.iloc[j][profiles[1::][i]]
    #         change_text = f"{percentage:.2f}"
    #         rounded_percentage = round(percentage, 2)
    #         x_min, x_max = ax.get_xlim()
    #
    #         if num_profiles > 2:
    #             bar.set_hatch(styles[i]["hatch"])
    #         bar.set_edgecolor("black")
    #         bar.set_linewidth(0.5)
    #
    #         # Place text to the left or right, if it is a regression/improvement
    #         if num_profiles == 2:
    #             if percentage > 0:
    #                 text_x = percentage + 0.02 * (x_max - x_min)
    #                 text_ha = "left"
    #             else:
    #                 text_x = percentage - 0.02 * (x_max - x_min)
    #                 text_ha = "right"
    #
    #             ax.text(
    #                 text_x,
    #                 j - 0.2,
    #                 # j - 0.35 + 0.45 * i,
    #                 change_text + '%',
    #                 ha=text_ha,
    #                 color=(
    #                     BRIGHTRED
    #                     if rounded_percentage > 0
    #                     else BRIGHTGREEN if rounded_percentage < 0 else BRIGHTYELLOW
    #                 ),
    #                 fontsize=ANNOTATION_FONT_SIZE,
    #                 fontweight="bold",
    #             )

    ax.set(ylabel=None)
    ax.set_xlabel(xlabel, fontsize=PLOT_FONT_SIZE, color=BLACK)
    ax.xaxis.set_label_position("top")

    for y in range(num_tests):
        ax.axhline(y, color='gray', linestyle='solid', linewidth=0.5, alpha=0.3)

    ax.axvline(0, color='black', linestyle='solid', linewidth=0.75, alpha=0.6)

    df["Test"] = df["Test"].replace({
        "openssl-3.0.1": "openssl"
    })
    if yticks:
        ax.set_yticks(range(len(df)))
        ax.set_yticklabels(df["Test"])
    else:
        ax.set_yticks([])


class ResultsExtractor:
    def __init__(self, results_dir):
        self.results_dir = results_dir
        self.compute_results()

    def compute_results(self, results_dir):
        pass

    def write_results(self, results, results_file):
        pass

    def merge_results(self, results_file):
        pass

    def plot_results(self, results_file, plot_dir, ax):
        pass


class RuntimeResultsExtractor(ResultsExtractor):
    def compute_results(self):
        self.results = []

        for test in os.listdir(self.results_dir + "/test-results"):
            path = os.path.join(
                self.results_dir + "/test-results",
                test,
                FLAG,
                "composite.xml",
            )
            tree = ET.parse(path)
            root = tree.getroot()

            for result in root.findall(".//Result"):
                identifier = result.find("Identifier").text.replace("local/", "")
                description = result.find("Description").text or "No description"
                scale = result.find("Scale").text
                proportion = result.find("Proportion").text
                for entry in result.findall(".//Data/Entry"):
                    profile = entry.find("Identifier").text
                    value = entry.find("Value").text

                    self.results.append(
                        (
                            identifier,
                            description,
                            scale,
                            proportion,
                            profile,
                            value,
                        )
                    )

        self.results.sort(key=lambda x: (x[0], x[4], x[1]))

    def merge_results(self, results_file):
        df = pd.DataFrame(self.results, columns=[
            "Test", "Description", "Scale", "Proportion", "Profile", "Value"
        ])
        df["Value"] = pd.to_numeric(df["Value"])
        df = df.pivot_table(
            index=["Test", "Description", "Scale", "Proportion"],
            columns="Profile",
            values="Value",
        )
        df.to_csv(results_file, sep=";")
        return df.reset_index()

    def plot_results(self, df, ax, styles, yticks=False):
        profile_names = [profile["name"] for profile in styles]
        for profile in profile_names[1::]:
            df[profile] = pd.Series(
                np.where(
                    df["Proportion"] == "HIB",
                    (df["base"] - df[profile]) / df[profile] * 100,
                    (df[profile] - df["base"]) / df["base"] * 100,
                ),
                index=df.index,
            )
            df[profile] = df.groupby("Test")[profile].transform("mean")

        df = df.drop(columns=["Scale", "Proportion", "Description", "base"])
        df = df.groupby("Test", as_index=False).mean(numeric_only=True)
        df = df.sort_values(by="Test", ascending=False)

        plot_relative(df, ax, "Run-time Performance (%)", styles, yticks=yticks)


class CompileTimeResultsExtractor(ResultsExtractor):
    def compute_results(self):
        self.results = []

        for test in os.listdir(self.results_dir + "/compile-time"):
            for profile in os.listdir(self.results_dir + "/compile-time/" + test):
                flag_dir = os.path.join(
                    self.results_dir, "compile-time", test, profile, FLAG
                )
                times = [
                    int(line.split("\t")[1])
                    for f in os.listdir(flag_dir)
                    for line in open(os.path.join(flag_dir, f)).read().splitlines()
                ]
                self.results += [
                    (test, profile, sum(times) / len(os.listdir(flag_dir)))
                ]

        self.results.sort(key=lambda x: (x[0], x[1]))

    def merge_results(self, results_file):
        df = pd.DataFrame(self.results, columns=[
            "Test", "Profile", "Compile Time"
        ])
        df["Compile Time"] = pd.to_numeric(df["Compile Time"])
        df = df.pivot_table(
            index=["Test"],
            columns="Profile",
            values="Compile Time",
        )
        df.to_csv(results_file, sep=";")
        return df.reset_index()

    def plot_results(self, df, ax, styles, relative=False, yticks=False):
        profile_names = [profile["name"] for profile in styles]

        if relative:
            for profile in profile_names[1::]:
                df[profile] = pd.Series(
                    (df[profile] - df["base"]) / df["base"] * 100,
                    index=df.index,
                )
            df = df.drop(columns=["base"])
        else:
            # Compile time in seconds
            df[profile_names] = df[profile_names] / 1000

        df.sort_values(by="Test", ascending=False, inplace=True)
        if relative:
            plot_relative(df, ax, "Compile Time (%)", styles, yticks=yticks)
        else:
            plot_absolute(df, ax, "Compile Time (sec)", styles, log=True, yticks=yticks)

class ObjectSizeResultsExtractor(ResultsExtractor):
    def compute_results(self):
        self.results = []

        for test in os.listdir(self.results_dir + "/object-size"):
            for profile in os.listdir(self.results_dir + "/object-size/" + test):
                profile_path = os.path.join(
                    self.results_dir + "/object-size", test, profile, f"{FLAG}.txt"
                )
                with open(profile_path, "r") as f:
                    sum = 0
                    for i, line in enumerate(f):
                        if i == 0 or line.startswith("   text"): continue
                        text, _, _, _, _, _ = line.split("\t")
                        sum += int(text)
                    self.results += [(test, profile, sum)]

        self.results.sort(key=lambda x: (x[0], x[1]))

    def merge_results(self, results_file):
        df = pd.DataFrame(self.results, columns=[
            "Test", "Profile", "Size"
        ])
        df["Size"] = pd.to_numeric(df["Size"])
        df = df.pivot_table(
            index=["Test"],
            columns="Profile",
            values="Size",
        )
        df.to_csv(results_file, sep=";")
        return df.reset_index()

    def plot_results(self, df, ax, styles, relative=False, yticks=False):
        profile_names = [profile["name"] for profile in styles]

        if relative:
            for profile in profile_names[1::]:
                df[profile] = pd.Series(
                    (df[profile] - df["base"]) / df["base"] * 100,
                    index=df.index,
                )
            df = df.drop(columns=["base"])
        else:
            # Object size in kB
            df[profile_names] = df[profile_names] / 1024

        df.sort_values(by="Test", ascending=False, inplace=True)
        if relative:
            plot_relative(df, ax, "Binary Size (%)", styles, yticks=yticks)
        else:
            plot_absolute(df, ax, "Binary Size (kB)", styles, log=True, yticks=yticks)


class MemoryUsageResultsExtractor(ResultsExtractor):
    def compute_results(self):
        self.results = []
        for test in os.listdir(self.results_dir + "/memory-usage"):
            for profile in os.listdir(self.results_dir + "/memory-usage/" + test):
                flag_dir = os.path.join(
                    self.results_dir, "memory-usage", test, profile, FLAG
                )
                mem_usage = []
                for f in os.listdir(flag_dir):
                    with open(os.path.join(flag_dir, f), "r") as f:
                        for line in f:
                            if re.match(r"^\d+$", line.strip()):
                                mem_usage += [int(line.strip())]

                self.results += [
                    (test, profile, max(mem_usage) / len(os.listdir(flag_dir)))
                ]

    def merge_results(self, results_file):
        df = pd.DataFrame(self.results, columns=[
            "Test", "Profile", "Peak Memory Usage"
        ])
        df["Peak Memory Usage"] = pd.to_numeric(df["Peak Memory Usage"])
        df = df.pivot_table(
            index=["Test"],
            columns="Profile",
            values="Peak Memory Usage",
        )
        df.to_csv(results_file, sep=";")
        return df.reset_index()

    def plot_results(self, df, ax, styles, relative=False, yticks=False):
        profile_names = [profile["name"] for profile in styles]

        if relative:
            for profile in profile_names[1::]:
                df[profile] = pd.Series(
                    (df[profile] - df["base"]) / df["base"] * 100,
                    index=df.index,
                )
            df = df.drop(columns=["base"])
        else:
            # Peak memory usage in MB
            df[profile_names] = df[profile_names] / 1024

        df.sort_values(by="Test", ascending=False, inplace=True)
        if relative:
            plot_relative(df, ax, "Peak Memory Usage (%)", styles, yticks=yticks)
        else:
            plot_absolute(df, ax, "Peak Memory Usage (MB)", styles, log=False, yticks=yticks)

class InstructionCountResultsExtractor(ResultsExtractor):
    def compute_results(self):
        self.results = []

        for test in os.listdir(self.results_dir + "/instr-count"):
            for profile in os.listdir(self.results_dir + "/instr-count/" + test):
                file = os.path.join(
                    self.results_dir, "instr-count", test, profile, f"{FLAG}.txt"
                )
                instr_counts = [
                    int(line.split(";")[1])
                    for line in open(file).read().splitlines()
                ]
                self.results += [
                    (test, profile, sum(instr_counts))
                ]

        self.results.sort(key=lambda x: (x[0], x[1]))

    def merge_results(self, results_file):
        df = pd.DataFrame(self.results, columns=[
            "Test", "Profile", "Instruction Count"
        ])
        df["Instruction Count"] = pd.to_numeric(df["Instruction Count"])
        df = df.pivot_table(
            index=["Test"],
            columns="Profile",
            values="Instruction Count",
        )
        df.to_csv(results_file, sep=";")
        return df.reset_index()

    def plot_results(self, df, ax, styles, relative=False, yticks=False):
        profile_names = [profile["name"] for profile in styles]

        if relative:
            for profile in profile_names[1::]:
                df[profile] = pd.Series(
                    (df[profile] - df["base"]) / df["base"] * 100,
                    index=df.index,
                )
            df = df.drop(columns=["base"])

        df.sort_values(by="Test", ascending=False, inplace=True)
        if relative:
            plot_relative(df, ax, "IR Instruction Count (%)", styles, yticks=yticks)
        else:
            plot_absolute(df, ax, "IR Instruction Count", styles, log=True, yticks=yticks)

class AliveResultsExtractor(ResultsExtractor):
    def compute_results(self):
        return
        self.results = []

        for test in os.listdir(self.results_dir + "/alive"):
            for profile in os.listdir(self.results_dir + "/alive/" + test):
                flag_dir = os.path.join(
                    self.results_dir, "alive", test, profile, FLAG
                )
                times = [
                    int(line.split("\t")[1])
                    for f in os.listdir(flag_dir)
                    for line in open(os.path.join(flag_dir, f)).read().splitlines()
                ]
                self.results += [
                    (test, profile, sum(times) / len(os.listdir(flag_dir)))
                ]

        self.results.sort(key=lambda x: (x[0], x[1]))

    def merge_results(self, results_file):
        df = pd.DataFrame(self.results, columns=[
            "Test", "Profile", "Time"
        ])
        df["Time"] = pd.to_numeric(df["Time"])
        df = df.pivot_table(
            index=["Test"],
            columns="Profile",
            values="Time",
        )
        df.to_csv(results_file, sep=";")
        return df.reset_index()

    def plot_results(self, df, ax, styles, relative=False, yticks=False):
        profile_names = [profile["name"] for profile in styles]

        if relative:
            for profile in profile_names[1::]:
                df[profile] = pd.Series(
                    (df[profile] - df["base"]) / df["base"] * 100,
                    index=df.index,
                )
            df = df.drop(columns=["base"])
        else:
            df[profile_names] = df[profile_names] / (60 * 60)

        df.sort_values(by="Test", ascending=False, inplace=True)
        if relative:
            plot_relative(df, ax, "Alive2 Optimization Verification Time (%)", styles, yticks=yticks)
        else:
            plot_absolute(df, ax, "Alive2 Optimization Verification Time (hours)", styles, log=False, yticks=yticks)


class TestInfoExtractor(ResultsExtractor):
    def __init__(self, results_dir, test_profiles_dir):
        super().__init__(results_dir)
        self.test_profiles_dir = test_profiles_dir

    def compute_results(self):
        self.results = []

        for test in os.listdir(self.results_dir + "/object-size"):
            profile = os.listdir(self.results_dir + "/object-size/" + test)[0]
            profile_path = os.path.join(
                self.results_dir + "/object-size", test, profile, f"{FLAG}.txt"
            )
            loc = 0
            with open(profile_path, "r") as f:
                for line in f:
                    # File output has a tab
                    if (len(line.split("\t"))) != 3:
                        continue
                    size, _, type = line.split("\t")
                    if "C source" in type or "C++ source" in type:
                        loc += int(size)

            with open(
                os.path.join(
                    args.test_profiles_dir, "local", test, "test-definition.xml"
                ),
                "r",
            ) as f:
                tree = ET.parse(f)
                root = tree.getroot()

                version = root.find(".//AppVersion").text
                description = root.find(".//Description").text

            self.results += [(test, version, description, loc)]

        self.results.sort(key=lambda x: x[0])

    def write_results(self, results_file):
        print(f"Writing line of code results to {results_file}")
        with open(results_file, "w") as f:
            f.write("Test;Version;Description;LOC\n")
            for test_name, version, description, loc in self.results:
                f.write(f"{test_name};{version};{description};{loc}\n")

    def merge_results(self, results_file):
        raise NotImplementedError

    def plot_results(self, results_file, ax):
        raise NotImplementedError


class AsmSizeResultsExtractor(ResultsExtractor):
    def compute_results(self):
        self.results = []
        self.function_sizes = {}
        self.all_functions = {}
        self.diff_functions = {}
        self.diff_loose_functions = {}  # Add new dictionary for loose diff

        for test in os.listdir(self.results_dir + "/asm-diff"):
            self.function_sizes[test] = {}

            for profile in os.listdir(self.results_dir + "/asm-diff/" + test):
                self.function_sizes[test][profile] = {}
                profile_path = os.path.join(
                    self.results_dir + "/asm-diff", test, profile, FLAG, "sizes.txt"
                )

                if not os.path.exists(profile_path):
                    continue

                with open(profile_path, "r") as f:
                    for line in f:
                        size_str, func_name = line.strip().split()
                        size = int(size_str)
                        self.function_sizes[test][profile][func_name] = size
                        self.results.append((test, profile, func_name, size))

                all_functions_path = os.path.join(
                    self.results_dir + "/asm-diff", test, FLAG, "all.txt"
                )
                if not os.path.exists(all_functions_path):
                    continue
                with open(all_functions_path, "r") as f:
                    self.all_functions[test] = sum(1 for _ in f)
                diff_functions_path = os.path.join(
                    self.results_dir + "/asm-diff", test, FLAG, "diff.txt"
                )
                if not os.path.exists(diff_functions_path):
                    continue
                with open(diff_functions_path, "r") as f:
                    self.diff_functions[test] = sum(1 for _ in f)
                # Add reading of loose diff file
                diff_loose_path = os.path.join(
                    self.results_dir + "/asm-diff", test, FLAG, "diff_loose.txt"
                )
                if not os.path.exists(diff_loose_path):
                    continue
                with open(diff_loose_path, "r") as f:
                    self.diff_loose_functions[test] = sum(1 for _ in f)

        self.results.sort(key=lambda x: (x[0], x[1], x[3], x[2]))

    def write_results(self, results_file):
        print(f"Writing ASM function size results to {results_file}")
        with open(results_file, "w") as f:
            f.write("Test;Profile;Function;Size\n")
            for test, profile, func_name, size in self.results:
                func_name = func_name.replace(";", "\\;")
                f.write(f"{test};{profile};{func_name};{size}\n")

    def merge_results(self, results_file):
        # Not applicable for this analysis
        pass

    def get_timeout_status(self, test):
        timeout_file = os.path.join(self.results_dir, 'asm-diff', test, FLAG, 'timeout.txt')
        if os.path.exists(timeout_file):
            with open(timeout_file, 'r') as f:
                return f.read().strip() == 'y'
        return False

    def plot_results(self, results_file, plot_dir, styles):
        plot_file_combined = f"{plot_dir}/asm-plots.pdf"
        print(f"Plotting combined ASM results to {plot_file_combined}")

        # Extract profile names and colors from styles
        profile_colors = {style["name"]: style["color"] for style in styles}
        profile_names = [style["name"] for style in styles]

        # First pass: collect data
        test_data = {}
        tests = []
        global_min_size = float("inf")
        global_max_size = float("-inf")
        global_min_diff = float("inf")
        global_max_diff = float("-inf")

        for test in self.function_sizes:
            available_profiles = [p for p in profile_names if p in self.function_sizes[test]]

            if len(available_profiles) < 2:
                continue

            # Use base as reference if available, otherwise use first profile
            ref_profile = "base" if "base" in available_profiles else available_profiles[0]
            compare_profiles = [p for p in available_profiles if p != ref_profile]

            if not compare_profiles:
                continue

            ref_sizes = self.function_sizes[test][ref_profile]

            # Collect data for all profiles
            profile_data = {ref_profile: {"sizes": [], "funcs": set(ref_sizes.keys())}}
            common_funcs = set(ref_sizes.keys())

            for profile in compare_profiles:
                profile_sizes = self.function_sizes[test][profile]
                profile_data[profile] = {"sizes": [], "funcs": set(profile_sizes.keys())}
                common_funcs &= set(profile_sizes.keys())

            if not common_funcs:
                continue

            # Calculate sizes and differences
            ref_func_sizes = [ref_sizes[func] for func in common_funcs]
            profile_data[ref_profile]["sizes"] = ref_func_sizes

            all_size_diffs = {}
            for profile in compare_profiles:
                profile_sizes = self.function_sizes[test][profile]
                profile_func_sizes = [profile_sizes[func] for func in common_funcs]
                size_diffs = [profile_sizes[func] - ref_sizes[func] for func in common_funcs]

                profile_data[profile]["sizes"] = profile_func_sizes
                all_size_diffs[profile] = size_diffs

                global_min_size = min(global_min_size, min(profile_func_sizes))
                global_max_size = max(global_max_size, max(profile_func_sizes))
                global_min_diff = min(global_min_diff, min(size_diffs))
                global_max_diff = max(global_max_diff, max(size_diffs))

            global_min_size = min(global_min_size, min(ref_func_sizes))
            global_max_size = max(global_max_size, max(ref_func_sizes))

            # Calculate totals and summary stats for primary comparison (first compare profile)
            primary_profile = compare_profiles[0]
            ref_total = sum(ref_func_sizes)
            primary_total = sum(profile_data[primary_profile]["sizes"])
            total_diff = primary_total - ref_total

            min_diff = min(all_size_diffs[primary_profile])
            max_diff = max(all_size_diffs[primary_profile])

            tests.append(test)
            test_data[test] = {
                "ref_profile": ref_profile,
                "compare_profiles": compare_profiles,
                "profile_data": profile_data,
                "all_size_diffs": all_size_diffs,
                "ref_total": ref_total,
                "primary_total": primary_total,
                "total_diff": total_diff,
                "min_diff": min_diff,
                "max_diff": max_diff,
            }

        tests.sort()
        n_tests = len(tests)

        if n_tests == 0:
            print("No tests with sufficient data to plot")
            return

        n_cols = 4
        n_rows = math.ceil(n_tests / 2)

        fig, axes = plt.subplots(
            n_rows, n_cols,
            figsize=(14, 1.75 * n_rows),
            sharex=False
        )

        axes = axes.flatten()

        all_handles = []
        all_labels = []

        # Plot data
        for i, test in enumerate(tests):
            col_offset = (i % 2) * 2
            row_index = i // 2
            flat_index_size = row_index * n_cols + col_offset
            flat_index_diff = row_index * n_cols + col_offset + 1

            if flat_index_diff >= len(axes):
                continue

            ax_size = axes[flat_index_size]
            ax_diff = axes[flat_index_diff]

            ax_size.set_facecolor(BACKGROUND)
            ax_diff.set_facecolor(BACKGROUND)

            data = test_data[test]
            ref_profile = data["ref_profile"]
            compare_profiles = data["compare_profiles"]
            profile_data = data["profile_data"]

            # Construct summary strings
            summary_shift = f"{data['total_diff']:+,d} bytes"
            summary_funcs = ""
            if test in self.diff_functions and test in self.all_functions and test in self.diff_loose_functions:
                num_changed = self.diff_loose_functions[test]
                total_funcs = self.all_functions[test]
                percent = (num_changed / total_funcs) * 100
                summary_funcs = f"{num_changed:,d}/{total_funcs:,d} ({percent:.1f}%)"

            if test == "openssl-3.0.1":
                test = "openssl"
            shift_title = f"{test}: {summary_shift}" if len(profile_names) == 2 else test
            function_title = f"{test}: {summary_funcs}" if len(profile_names) == 2 else test

            # Function Size Plot - overlapping histograms
            all_sizes = []
            for profile in [ref_profile] + compare_profiles:
                all_sizes.extend(profile_data[profile]["sizes"])

            test_min_size = min(all_sizes)
            test_max_size = max(all_sizes)
            test_log_min = np.log10(max(1, test_min_size))
            test_log_max = np.log10(test_max_size)
            test_size_bins = np.logspace(test_log_min, test_log_max, 70)

            # Plot reference profile first
            ax_size.hist(
                profile_data[ref_profile]["sizes"],
                bins=test_size_bins,
                alpha=0.6,
                color=profile_colors[ref_profile],
                label=ref_profile.capitalize(),
            )

            # Overlay comparison profiles
            for profile in compare_profiles:
                ax_size.hist(
                    profile_data[profile]["sizes"],
                    bins=test_size_bins,
                    alpha=0.6,
                    color=profile_colors[profile],
                    label=profile.capitalize(),
                )

            ax_size.set_xscale("log")
            ax_size.set_yscale("linear")
            ax_size.set_title(f"{shift_title}", fontsize=PLOT_FONT_SIZE)

            # Size Difference Plot - overlay multiple differences
            all_diffs = []
            for profile in compare_profiles:
                all_diffs.extend(data["all_size_diffs"][profile])

            test_max_abs_diff = max(abs(min(all_diffs)), abs(max(all_diffs)))
            test_diff_bins = np.linspace(-test_max_abs_diff, test_max_abs_diff, 151)

            # Plot differences for each comparison profile
            for profile in compare_profiles:
                ax_diff.hist(
                    data["all_size_diffs"][profile],
                    bins=test_diff_bins,
                    alpha=0.6,
                    color=profile_colors[profile],
                    label=f"{profile} - {ref_profile}",
                )

            ax_diff.set_yscale("log")
            ax_diff.set_xlim(-test_max_abs_diff * 1.1, test_max_abs_diff * 1.1)
            ax_diff.set_title(f"{function_title}", fontsize=PLOT_FONT_SIZE)

            # Extract legend handles once
            if i == 0:
                for profile in [ref_profile] + compare_profiles:
                    # patch = plt.Rectangle((0, 0), 1, 1, fc=profile_colors[profile], alpha=0.5)
                    patch = plt.Rectangle((0, 0), 1, 1, fc=profile_colors[profile])
                    all_handles.append(patch)
                    all_labels.append(profile)

            # Gridlines
            ax_size.grid(True, which="both", axis="y", linestyle="dotted", color="#8B949E", alpha=0.5)
            ax_diff.grid(True, which="both", axis="x", linestyle="dotted", color="#8B949E", alpha=0.5)

        # Hide unused axes
        used_axes_count = 2 * n_tests
        for i in range(used_axes_count, len(axes)):
            axes[i].axis("off")

        # Set X-axis labels for bottom row
        last_row_start_index = (n_rows - 1) * n_cols
        for i in range(last_row_start_index, last_row_start_index + n_cols):
            if i < len(axes) and axes[i].get_visible():
                if (i % n_cols) == 0 or (i % n_cols) == 2:
                    axes[i].set_xlabel("Function Size (bytes)", fontsize=PLOT_FONT_SIZE, color=BLACK)
                elif (i % n_cols) == 1 or (i % n_cols) == 3:
                    axes[i].set_xlabel("Size Difference (bytes)", fontsize=PLOT_FONT_SIZE, color=BLACK)

        def label_name(name):
            if name == "base":
                return "Baseline"
            if name == "byte":
                return "Byte Type"
            if name == "byte-noopt":
                return "Byte Type (without optimizations)"
            if name == "byte-rust":
                return "Byte Type (with load + bytecast combining)"
            if name == "freeze":
                return "Poison Uninitialized Memory"

        # Create figure legend
        fig.legend(
            handles=all_handles,
            labels=map(label_name, all_labels),
            loc='upper center',
            ncol=len(all_handles),
            fontsize=PLOT_FONT_SIZE,
            frameon=True,
            framealpha=1,
            bbox_to_anchor=(0.5, 1)
        )

        plt.tight_layout(rect=[0, 0, 1, 0.98])
        plt.savefig(plot_file_combined, dpi=300, bbox_inches="tight")
        plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert results to CSV")
    parser.add_argument("results_dir", type=str, help="Results directory")
    parser.add_argument("test_profiles_dir", type=str, help="Test profiles directory")
    parser.add_argument("optimization_flag", type=str, help="Optimization flag")
    args = parser.parse_args()

    results_dir = args.results_dir
    if not os.path.isdir(results_dir):
        print(f"Results directory {results_dir} does not exist!")
        exit(1)

    FLAG = args.optimization_flag.replace("-", "")

    CSV_PATH = results_dir + "/csv"
    RUNTIME_RESULTS_FILE = CSV_PATH + "/runtime.csv"
    COMPILE_TIME_RESULTS_FILE = CSV_PATH + "/compile-time.csv"
    OBJECT_SIZE_RESULTS_FILE = CSV_PATH + "/object-size.csv"
    MEMORY_USAGE_RESULTS_FILE = CSV_PATH + "/memory-usage.csv"
    INSTRUCTION_COUNT_RESULTS_FILE = CSV_PATH + "/instruction-count.csv"
    ALIVE_RESULTS_FILE = CSV_PATH + "/alive.csv"
    ASM_SIZE_RESULTS_FILE = CSV_PATH + "/asm-size.csv"
    TEST_INFO_FILE = CSV_PATH + "/test-info.csv"

    if not os.path.exists(CSV_PATH):
        os.makedirs(CSV_PATH)

    compile_time = CompileTimeResultsExtractor(results_dir)
    runtime = RuntimeResultsExtractor(results_dir)
    object_size = ObjectSizeResultsExtractor(results_dir)
    memory_usage = MemoryUsageResultsExtractor(results_dir)
    instruction_count = InstructionCountResultsExtractor(results_dir)
    alive = AliveResultsExtractor(results_dir)
    asm_size = AsmSizeResultsExtractor(results_dir)
    # test_info = TestInfoExtractor(results_dir, args.test_profiles_dir)

    PLOT_PATH = results_dir + "/plots"
    if not os.path.exists(PLOT_PATH):
        os.makedirs(PLOT_PATH)

    compile_time_df = pd.read_csv(results_dir + "/csv/compile-time.csv", sep=";")
    runtime_df = pd.read_csv(results_dir + "/csv/runtime.csv", sep=";")
    memory_usage_df = pd.read_csv(results_dir + "/csv/memory-usage.csv", sep=";")
    object_size_df = pd.read_csv(results_dir + "/csv/object-size.csv", sep=";")
    instruction_count_df = pd.read_csv(results_dir + "/csv/instruction-count.csv", sep=";")
    alive_df = pd.read_csv(results_dir + "/csv/alive.csv", sep=";")

    # compile_time_df = compile_time.merge_results(COMPILE_TIME_RESULTS_FILE)
    # runtime_df = runtime.merge_results(RUNTIME_RESULTS_FILE)
    # memory_usage_df = memory_usage.merge_results(MEMORY_USAGE_RESULTS_FILE)
    # object_size_df = object_size.merge_results(OBJECT_SIZE_RESULTS_FILE)
    # instruction_count_df = instruction_count.merge_results(INSTRUCTION_COUNT_RESULTS_FILE)

    # fig, axes = plt.subplots(2, 3, figsize=(12, 10))
    # ax1 = axes[0, 0]
    # ax2 = axes[0, 1]
    # ax3 = axes[0, 2]
    # ax4 = axes[1, 0]
    # ax5 = axes[1, 1]
    # axes[1, 2].set_visible(False)  # Hide the last one

    # fig, _ = plt.subplots(figsize=(12, 10))
    # gs = GridSpec(2, 9, figure=fig, height_ratios=[1, 1])  # 9 columns instead of 6
    # ax1 = fig.add_subplot(gs[0, 0:3])   # 3 columns
    # ax2 = fig.add_subplot(gs[0, 3:6])   # 3 columns
    # ax3 = fig.add_subplot(gs[0, 6:9])   # 3 columns
    # ax4 = fig.add_subplot(gs[1, 1:4])   # 3 columns, centered (starts at 1)
    # ax5 = fig.add_subplot(gs[1, 5:8])   # 3 columns, centered (starts at 5)

    # fig, _ = plt.subplots(figsize=(12, 10))
    fig, axs = plt.subplots(figsize=(8, 2))
    # gs = GridSpec(2, 12, figure=fig, height_ratios=[1, 1],
    #   hspace=0.15,   # Space between rows
    #   wspace=0.1 ,  # Space between columns
    #   left=0.08,    # Left margin
    #   right=0.98,   # Right margin
    #   top=0.94,     # Top margin
    #   bottom=0.05   # Bottom margin
    # )
    # ax1 = fig.add_subplot(gs[0, 0:4])
    # ax2 = fig.add_subplot(gs[0, 4:8])
    # ax3 = fig.add_subplot(gs[0, 8:12])
    # ax4 = fig.add_subplot(gs[1, 2:6])
    # ax5 = fig.add_subplot(gs[1, 6:10])

    styles = [
        {"name": "base", "color": "#E69F00", "hatch": None},
        # {"name": "byte-noopt", "color": "#CC3311", "hatch": None},
        {"name": "byte", "color": "#0077BB", "hatch": None},
        # {"name": "byte-rust", "color": "#EE7733", "hatch": None},
        # # {"name": "freeze", "color": "#009988", "hatch": None},
        # {"name": "byte-rust", "color": "#009988", "hatch": None},
    ]

    relative=False
    # compile_time.plot_results(compile_time_df, ax1, styles, relative=relative, yticks=True)
    # runtime.plot_results(runtime_df, ax2, styles, yticks=False)
    # memory_usage.plot_results(memory_usage_df, ax3, styles, relative=relative, yticks=False)
    # object_size.plot_results(object_size_df, ax4, styles, relative=relative, yticks=True)
    # instruction_count.plot_results(instruction_count_df, ax5, styles, relative=relative, yticks=False)
    alive.plot_results(alive_df, axs, styles, relative=relative, yticks=True)
    # asm_size.plot_results(ASM_SIZE_RESULTS_FILE, PLOT_PATH, styles)

    patches = []
    for style in styles:
        patches += [
            plt.Rectangle((0, 0), 1, 1, fc=style["color"], hatch=style["hatch"], edgecolor=BLACK, linewidth=1)
        ]

    # If there are only two profiles, emit red and green hatches
    # (improvement and regression)
    if len(styles) == 2:
        patches += [
            plt.Rectangle(
                 (0, 0), 1, 1, fc=GREEN, edgecolor=BLACK, linewidth=1
             ),
            plt.Rectangle(
                (0, 0), 1, 1, fc=RED, edgecolor=BLACK, linewidth=1
            )
        ]

    def label_name(name):
        if name == "base":
            return "Baseline"
        if name == "byte":
            return "Byte Type"
        if name == "byte-noopt":
            return "Byte Type (without optimizations)"
        if name == "byte-rust":
            return "Byte Type (with load + bytecast combining)"
        if name == "freeze":
            return "Poison Uninitialized Memory"

    fig.legend(
        handles=patches if not relative else patches[1::],
        labels = map(label_name, [style["name"] for style in (styles if not relative else styles[1:])]),
        loc="upper center",
        fontsize=10,
        frameon=True,
        framealpha=1,
        ncol=4,
        bbox_to_anchor=(0.5, 1.0)
    )

    # for ax in [ax1, ax2, ax3, ax4, ax5]:
    #     if ax.get_legend():
    #         ax.get_legend().remove()
    #
    # for ax in fig.axes:
    #     if ax not in [ax1, ax2, ax3, ax4, ax5]:
    #         fig.delaxes(ax)
    # for ax in axs.flat:
        # if ax.get_legend():
        #     ax.get_legend().remove()

    if axs.get_legend():
        axs.get_legend().remove()
    plt.tight_layout(rect=[0, 0, 1, 0.88])
    plt.savefig(PLOT_PATH + "/plots.pdf", dpi=300, bbox_inches="tight")
    plt.close()

