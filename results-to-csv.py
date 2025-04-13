import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
import xml.etree.ElementTree as ET
import argparse
import re
from matplotlib.ticker import AutoMinorLocator
from scipy import stats

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

    def plot_results(self, results_file, plot_dir):
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
                identifier = result.find("Identifier").text
                identifier = identifier.replace("local/", "")
                description = result.find("Description").text or "No description"
                scale = result.find("Scale").text
                proportion = result.find("Proportion").text
                for entry in result.findall(".//Data/Entry"):
                    profile = entry.find("Identifier").text
                    value = entry.find("Value").text or float("nan")

                    # Calculate standard deviation from raw string
                    std_dev = 0.0
                    rawstring = entry.find("RawString").text
                    raw_values = [float(val.strip()) for val in rawstring.split(":")]

                    # Calculate mean
                    mean_value = sum(raw_values) / len(raw_values) if raw_values else 0

                    # Calculate standard deviation using the formula: σ = √(1/N * Σ(x_i - x̄)²)
                    if raw_values:
                        squared_diff_sum = sum(
                            (x - mean_value) ** 2 for x in raw_values
                        )
                        std_dev = (squared_diff_sum / len(raw_values)) ** 0.5

                    # Calculate RSD: RSD (%) = (σ / x̄) * 100
                    rsd = (std_dev / mean_value * 100) if mean_value != 0 else 0

                    self.results.append(
                        (
                            identifier,
                            description,
                            scale,
                            proportion,
                            profile,
                            value,
                            std_dev,
                            rsd,
                        )
                    )

        self.results.sort(key=lambda x: (x[0], x[4], x[1]))

    def write_results(self, results_file):
        print(f"Writing runtime results to {results_file}")
        with open(results_file, "w") as f:
            f.write("Test;Description;Scale;Proportion;Profile;Value;StdDev;RSD\n")
            for (
                test,
                description,
                scale,
                proportion,
                profile,
                value,
                std_dev,
                rsd,
            ) in self.results:
                f.write(
                    f"{test};{description};{scale};{proportion};{profile};{value};{std_dev};{rsd}\n"
                )

    def merge_results(self, results_file):
        df = pd.read_csv(results_file, sep=";")
        pivot_table = df.pivot_table(
            index=["Test", "Description", "Scale", "Proportion"],
            columns="Profile",
            values="Value",
        )
        pivot_table.to_csv(results_file, sep=";")

    def plot_results(self, results_file, plot_dir):
        plot_file = f"{plot_dir}/runtime.svg"
        print(f"Plotting runtime results to {plot_file}")

        # Read the data once
        df = pd.read_csv(results_file, sep=";")

        # Create dictionaries for standard deviation, RSD, and mean values by test and profile
        std_dev_data = {}
        rsd_data = {}
        mean_data = {}
        for _, row in df.iterrows():
            key = (row["Test"], row["Profile"])
            std_dev_data[key] = row["StdDev"]
            rsd_data[key] = row["RSD"]
            mean_data[key] = row["Value"]

        num_tests = len(df["Test"].unique())
        height = max(6, 0.5 * num_tests)
        _, ax = plt.subplots(figsize=(8, height))
        ax.set_facecolor(BACKGROUND)

        # Pivot the data and sort by Test
        df_pivot = df.pivot_table(
            index=("Test", "Description", "Scale", "Proportion"),
            columns="Profile",
            values="Value",
        ).reset_index()
        df_pivot.sort_values(by="Test", ascending=False, inplace=True)

        df_percentage = pd.Series(
            np.where(
                df_pivot["Proportion"] == "HIB",
                (df_pivot["base"] - df_pivot["byte"]) / df_pivot["byte"] * 100,
                (df_pivot["byte"] - df_pivot["base"]) / df_pivot["base"] * 100,
            ),
            index=df_pivot.index,
        )

        df_pivot["Percentage"] = df_percentage

        # Group by Test and calculate the average percentage regression
        avg_percentage = df_pivot.groupby("Test")["Percentage"].mean().reset_index()
        avg_percentage.set_index("Test", inplace=True)
        avg_percentage.sort_values(by="Test", inplace=True, ascending=False)
        avg_percentage["Percentage"] = avg_percentage["Percentage"].astype(float)

        # Set colors based on regression percentage
        colors = [
            GREEN if percentage < 0 else RED
            for percentage in avg_percentage["Percentage"]
        ]

        # Prevent annotations from going outside the plot
        min_percentage = avg_percentage.min().min()
        max_percentage = avg_percentage.max().max()

        ax.set_xlim(min(-2, min_percentage * 2), max(2, max_percentage * 2))

        avg_percentage["Percentage"].plot(kind="barh", ax=ax, color=colors, width=0.8)
        for container in ax.containers:
            for i, bar in enumerate(container.patches):
                percentage = avg_percentage.iloc[i]["Percentage"]
                change_text = f"{percentage:.2f}"
                rounded_percentage = round(percentage, 2)
                x_min, x_max = ax.get_xlim()
                bar.set_edgecolor("black")
                bar.set_linewidth(1)

                # Get the test name for this bar
                test_name = avg_percentage.index[i]

                # Get RSD values for this test
                base_rsd = rsd_data.get((test_name, "base"), 0)
                byte_rsd = rsd_data.get((test_name, "byte"), 0)

                # Get the maximum RSD
                max_rsd = max(base_rsd, byte_rsd)

                # Add just the RSD percentage to the annotation
                rsd_text = f" ± {max_rsd:.2f}%"

                # Calculate text position for consistent alignment
                # For positive percentages, place text to the right of the bar
                # For negative percentages, place text to the left of the bar
                if percentage > 0:
                    # For positive values, position text after the bar
                    text_x = percentage + 0.02 * (x_max - x_min)
                    text_ha = "left"  # Left-align text
                else:
                    # For negative values, position text before the bar
                    text_x = percentage - 0.02 * (x_max - x_min)
                    text_ha = "right"  # Right-align text

                ax.text(
                    text_x,
                    i - 0.1,
                    change_text + rsd_text,
                    ha=text_ha,  # Use the calculated alignment
                    color=(
                        BRIGHTRED
                        if rounded_percentage > 0
                        else BRIGHTGREEN if rounded_percentage < 0 else BRIGHTYELLOW
                    ),
                    fontsize=10,
                    fontweight="bold",
                )

        ax.set(ylabel=None)
        plt.xlabel(
            "Runtime regression relative to baseline (%)", fontsize=12, color="#24292F"
        )

        ax.grid(
            True,
            which="both",
            axis="x",
            linestyle="dotted",
            color="#8B949E",
            alpha=0.7,
        )

        ax.axvline(x=0, color="black", linestyle="dotted", linewidth=1)
        ax.axvline(x=1, color="black", linestyle="--", linewidth=1, alpha=0.2)
        ax.axvline(x=-1, color="black", linestyle="--", linewidth=1, alpha=0.2)
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        ax.tick_params(which="minor", length=4, color="#8B949E")
        plt.yticks(rotation=45, ha="right", fontsize=11, color="#24292F")

        plt.subplots_adjust(bottom=0.1, top=0.99, left=0.15, right=0.98)
        plt.savefig(plot_file)
        plt.close()


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

    def write_results(self, results_file):
        print(f"Writing compile time results to {results_file}")
        with open(results_file, "w") as f:
            f.write("Test;Profile;Compile Time\n")
            for test, profile, total in self.results:
                f.write(f"{test};{profile};{total}\n")

    def merge_results(self, results_file):
        df = pd.read_csv(results_file, sep=";")
        pivot_table = df.pivot_table(
            index=["Test"],
            columns="Profile",
            values="Compile Time",
        )
        pivot_table.to_csv(results_file, sep=";")

    def plot_results(self, results_file, plot_dir):
        plot_file = f"{plot_dir}/compile-time.svg"
        print(f"Plotting compile time results to {plot_file}")

        # Read data and convert compile time to seconds
        df = pd.read_csv(results_file, sep=";")
        df["Compile Time"] = df["Compile Time"] / 1000

        num_tests = len(df["Test"].unique())
        height = max(6, 0.5 * num_tests)
        _, ax = plt.subplots(figsize=(8, height))
        ax.set_facecolor(BACKGROUND)
        df = df.pivot_table(index="Test", columns="Profile", values="Compile Time")
        df = df[["byte", "base"]]
        df.sort_values(by="Test", ascending=False, inplace=True)
        df.plot(kind="barh", ax=ax, color=[BLUE, RED], width=0.7)

        for container in ax.containers:
            for bar in container.patches:
                if container == ax.containers[0]:
                    bar.set_hatch("/" * 4)
                else:
                    bar.set_hatch("." * 4)
                bar.set_edgecolor("black")
                bar.set_linewidth(1)

        ax.set(ylabel=None)
        plt.xlabel("Compile time (sec)", fontsize=12, color=BLACK)

        # Prevent annotations from going outside the plot
        max_value = df.max().max()
        ax.set_xlim(1, max_value * 1.12)

        # Tilt x-axis labels for better readability
        plt.yticks(rotation=45, ha="right", fontsize=11, color=BLACK)

        ax.grid(
            True,
            which="both",
            axis="x",
            linestyle="dotted",
            color="#8B949E",
            alpha=0.7,
        )

        # Annotate plots with regression percentage
        for i, test in enumerate(df.index):
            base_value = df.loc[test, "base"]
            byte_value = df.loc[test, "byte"]

            if not np.isnan(base_value):
                percentage_change = ((byte_value - base_value) / base_value) * 100
                if round(percentage_change, 2) == 0.00:
                    percentage_change *= percentage_change
                change_text = f"{percentage_change:.2f}%"
            else:
                change_text = "nan%"

            x_min, x_max = ax.get_xlim()
            rounded_percentage_change = round(percentage_change, 2)
            ax.text(
                max(
                    0.05 * (x_max - x_min),
                    max(base_value, byte_value) + 0.05 * (x_max - x_min),
                ),
                i - 0.1,
                change_text,
                ha="center",
                color=(
                    BRIGHTRED
                    if rounded_percentage_change > 0
                    else BRIGHTGREEN if rounded_percentage_change < 0 else BRIGHTYELLOW
                ),
                fontsize=10,
                fontweight="bold",
            )

        ax.legend(
            labels=["Prototype", "LLVM 19.1.0"],
            loc="upper right",
            fontsize=12,
            frameon=True,
            framealpha=1,
        )

        plt.subplots_adjust(bottom=0.1, top=0.99, left=0.15, right=0.98)
        plt.savefig(plot_file)
        plt.close()


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
                    for line in f:
                        size, _ = line.split("\t")
                        sum += int(size)
                    self.results += [(test, profile, sum)]

        self.results.sort(key=lambda x: (x[0], x[1]))

    def write_results(self, results_file):
        print(f"Writing object size results to {results_file}")
        with open(results_file, "w") as f:
            f.write("Test;Profile;Size\n")
            for test, profile, size in self.results:
                f.write(f"{test};{profile};{size}\n")

    def merge_results(self, results_file):
        df = pd.read_csv(results_file, sep=";")
        pivot_table = df.pivot_table(
            index=["Test"],
            columns="Profile",
            values="Size",
        )
        pivot_table.to_csv(results_file, sep=";")

    def plot_results(self, results_file, plot_dir):
        plot_file = f"{plot_dir}/object-size.svg"
        print(f"Plotting object size results to {plot_file}")

        # Read data and convert object size to MB
        df = pd.read_csv(results_file, sep=";")
        df["Size"] = df["Size"] / (1024 * 1024)

        num_tests = len(df["Test"].unique())
        height = max(6, 0.5 * num_tests)
        _, ax = plt.subplots(figsize=(8, height))
        ax.set_facecolor(BACKGROUND)
        df = df.pivot_table(index="Test", columns="Profile", values="Size")
        df = df[["byte", "base"]]
        df.sort_values(by="Test", ascending=False, inplace=True)
        df.plot(kind="barh", ax=ax, color=[BLUE, RED], width=0.7)

        for container in ax.containers:
            for bar in container.patches:
                if container == ax.containers[0]:
                    bar.set_hatch("/" * 4)
                else:
                    bar.set_hatch("." * 4)
                bar.set_edgecolor("black")
                bar.set_linewidth(1)

        ax.set(ylabel=None)
        plt.xlabel("Object size (MB)", fontsize=12, color=BLACK)

        # Prevent annotations from going outside the plot
        max_value = df.max().max()
        ax.set_xlim(1, max_value * 1.12)

        # Tilt x-axis labels for better readability
        plt.yticks(rotation=45, ha="right", fontsize=11, color=BLACK)

        ax.grid(
            True,
            which="both",
            axis="x",
            linestyle="dotted",
            color="#8B949E",
            alpha=0.7,
        )

        # Annotate plots with regression percentage
        for i, test in enumerate(df.index):
            base_value = df.loc[test, "base"]
            byte_value = df.loc[test, "byte"]

            if not np.isnan(base_value):
                percentage_change = ((byte_value - base_value) / base_value) * 100
                if round(percentage_change, 2) == 0.00:
                    percentage_change *= percentage_change
                change_text = f"{percentage_change:.2f}%"
            else:
                change_text = "nan%"

            rounded_percentage_change = round(percentage_change, 2)
            x_min, x_max = ax.get_xlim()
            ax.text(
                max(
                    0.08 * (x_max - x_min),
                    max(base_value, byte_value) + 0.05 * (x_max - x_min),
                ),
                i - 0.1,
                change_text,
                ha="center",
                color=(
                    BRIGHTRED
                    if rounded_percentage_change > 0
                    else BRIGHTGREEN if rounded_percentage_change < 0 else BRIGHTYELLOW
                ),
                fontsize=10,
                fontweight="bold",
            )

        ax.legend(
            labels=["Prototype", "LLVM 19.1.0"],
            loc="upper right",
            fontsize=12,
            frameon=True,
            framealpha=1,
        )

        plt.subplots_adjust(bottom=0.1, top=0.99, left=0.15, right=0.98)
        plt.savefig(plot_file)
        plt.close()


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

    def write_results(self, results_file):
        print(f"Writing memory usage results to {results_file}")
        with open(results_file, "w") as f:
            f.write("Test;Profile;Peak Memory Usage\n")
            for test, profile, maximum in self.results:
                f.write(f"{test};{profile};{maximum}\n")

    def merge_results(self, results_file):
        df = pd.read_csv(results_file, sep=";")
        pivot_table = df.pivot_table(
            index=["Test"],
            columns="Profile",
            values="Peak Memory Usage",
        )
        pivot_table.to_csv(results_file, sep=";")

    def plot_results(self, results_file, plot_dir):
        plot_file = f"{plot_dir}/memory-usage.svg"
        print(f"Plotting memory usage results to {plot_file}")

        # Read data and convert memory usage to MB
        df = pd.read_csv(results_file, sep=";")
        df["Peak Memory Usage"] = df["Peak Memory Usage"] / 1024

        num_tests = len(df["Test"].unique())
        height = max(6, 0.5 * num_tests)
        _, ax = plt.subplots(figsize=(8, height))
        ax.set_facecolor(BACKGROUND)
        df = df.pivot_table(index="Test", columns="Profile", values="Peak Memory Usage")
        df = df[["byte", "base"]]
        df.sort_values(by="Test", ascending=False, inplace=True)
        df.plot(kind="barh", ax=ax, color=[BLUE, RED], width=0.7)

        for container in ax.containers:
            for bar in container.patches:
                if container == ax.containers[0]:
                    bar.set_hatch("/" * 4)
                else:
                    bar.set_hatch("." * 4)
                bar.set_edgecolor("black")
                bar.set_linewidth(1)

        ax.set(ylabel=None)
        plt.xlabel("Peak memory usage (MB)", fontsize=12, color=BLACK)

        # Prevent annotations from going outside the plot
        max_value = df.max().max()
        ax.set_xlim(1, max_value * 1.12)

        # Tilt x-axis labels for better readability
        plt.yticks(rotation=45, ha="right", fontsize=11, color=BLACK)

        ax.grid(
            True,
            which="both",
            axis="x",
            linestyle="dotted",
            color="#8B949E",
            alpha=0.7,
        )

        # Annotate plots with regression percentage
        for i, test in enumerate(df.index):
            base_value = df.loc[test, "base"]
            byte_value = df.loc[test, "byte"]

            if not np.isnan(base_value):
                percentage_change = ((byte_value - base_value) / base_value) * 100
                if round(percentage_change, 2) == 0.00:
                    percentage_change = abs(percentage_change)
                change_text = f"{percentage_change:.2f}%"
            else:
                change_text = "nan%"

            rounded_percentage_change = round(percentage_change, 2)
            x_min, x_max = ax.get_xlim()
            ax.text(
                max(
                    0.08 * (x_max - x_min),
                    max(base_value, byte_value) + 0.05 * (x_max - x_min),
                ),
                i - 0.1,
                change_text,
                ha="center",
                color=(
                    BRIGHTRED
                    if rounded_percentage_change > 0
                    else BRIGHTGREEN if rounded_percentage_change < 0 else BRIGHTYELLOW
                ),
                fontsize=10,
                fontweight="bold",
            )

        ax.legend(
            labels=["Prototype", "LLVM 19.1.0"],
            loc="upper right",
            fontsize=12,
            frameon=True,
            framealpha=1,
        )

        plt.subplots_adjust(bottom=0.1, top=0.99, left=0.15, right=0.98)
        plt.savefig(plot_file)
        plt.close()


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

    def plot_results(self, results_file, plot_dir):
        raise NotImplementedError


class AsmSizeResultsExtractor(ResultsExtractor):
    def compute_results(self):
        self.results = []
        self.function_sizes = {}
        self.all_functions = {}
        self.diff_functions = {}

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

    def plot_results(self, results_file, plot_dir):
        plot_file_size = f"{plot_dir}/asm-size.svg"
        plot_file_diff = f"{plot_dir}/asm-diff.svg"
        print(f"Plotting ASM function size to {plot_file_size}")
        print(f"Plotting ASM function size differences to {plot_file_diff}")

        # First pass: collect data
        test_data = {}
        tests = []
        global_min_size = float("inf")
        global_max_size = float("-inf")
        global_min_diff = float("inf")
        global_max_diff = float("-inf")

        for test in self.function_sizes:
            if (
                "base" not in self.function_sizes[test]
                or "byte" not in self.function_sizes[test]
            ):
                continue

            base_sizes = self.function_sizes[test]["base"]
            byte_sizes = self.function_sizes[test]["byte"]
            common_funcs = set(base_sizes.keys()) & set(byte_sizes.keys())

            if not common_funcs:
                continue

            # Store sizes for both profiles
            base_func_sizes = [base_sizes[func] for func in common_funcs]
            byte_func_sizes = [byte_sizes[func] for func in common_funcs]

            # Calculate size differences
            size_diffs = [byte_sizes[func] - base_sizes[func] for func in common_funcs]

            # Update global min/max for bin calculation
            global_min_size = min(
                global_min_size, min(base_func_sizes), min(byte_func_sizes)
            )
            global_max_size = max(
                global_max_size, max(base_func_sizes), max(byte_func_sizes)
            )
            global_min_diff = min(global_min_diff, min(size_diffs))
            global_max_diff = max(global_max_diff, max(size_diffs))

            # Calculate total sizes
            base_total = sum(base_func_sizes)
            byte_total = sum(byte_func_sizes)
            total_diff = byte_total - base_total

            # Find min/max differences for summary
            min_diff = min(size_diffs)
            max_diff = max(size_diffs)

            min_func = [
                func
                for func in common_funcs
                if byte_sizes[func] - base_sizes[func] == min_diff
            ][0]
            max_func = [
                func
                for func in common_funcs
                if byte_sizes[func] - base_sizes[func] == max_diff
            ][0]

            tests.append(test)
            test_data[test] = {
                "base_sizes": base_func_sizes,
                "byte_sizes": byte_func_sizes,
                "size_diffs": size_diffs,
                "base_total": base_total,
                "byte_total": byte_total,
                "total_diff": total_diff,
                "min_diff": min_diff,
                "max_diff": max_diff,
                "min_func": min_func,
                "max_func": max_func,
            }

        # Alphabetically sort the tests
        tests.sort()

        # Create figures for absolute sizes and differences
        n_tests = len(tests)
        fig_size, axes_size = plt.subplots(
            n_tests, 1, figsize=(10, 3 * n_tests), sharex=False
        )
        fig_diff, axes_diff = plt.subplots(
            n_tests, 1, figsize=(10, 3 * n_tests), sharex=False
        )
        if n_tests == 1:
            axes_size = [axes_size]
            axes_diff = [axes_diff]

        # Create histograms for each test
        for i, test in enumerate(tests):
            ax_size = axes_size[i]
            ax_diff = axes_diff[i]
            ax_size.set_facecolor(BACKGROUND)
            ax_diff.set_facecolor(BACKGROUND)

            data = test_data[test]

            # Calculate min and max size for this test
            test_min_size = min(min(data["base_sizes"]), min(data["byte_sizes"]))
            test_max_size = max(max(data["base_sizes"]), max(data["byte_sizes"]))
            test_log_min = np.log10(max(1, test_min_size))
            test_log_max = np.log10(test_max_size)
            # Use 70 bins for better visibility
            test_size_bins = np.logspace(test_log_min, test_log_max, 70)

            # Plot overlapping histograms with transparency for absolute sizes
            ax_size.hist(
                data["base_sizes"],
                bins=test_size_bins,
                alpha=0.5,
                color=RED,
                label="LLVM 19.1.0",
            )
            ax_size.hist(
                data["byte_sizes"],
                bins=test_size_bins,
                alpha=0.5,
                color=BLUE,
                label="Prototype",
            )

            # Set log scale on x-axis but linear scale on y-axis
            ax_size.set_xscale("log")
            ax_size.set_yscale("linear")

            # Calculate max difference for this specific test
            test_max_abs_diff = max(
                abs(min(data["size_diffs"])), abs(max(data["size_diffs"]))
            )
            # Create bins specific to this test's range
            test_diff_bins = np.linspace(-test_max_abs_diff, test_max_abs_diff, 151)

            # Plot histogram of size differences
            ax_diff.hist(
                data["size_diffs"],
                bins=test_diff_bins,
                color=BLUE,
                label="Size Difference",
            )

            # Set log scale for difference plot
            ax_diff.set_yscale("log")

            # Set x-axis limits for difference plot to be symmetric and specific to this test
            ax_diff.set_xlim(-test_max_abs_diff * 1.1, test_max_abs_diff * 1.1)

            # Add test name
            ax_size.set_ylabel(test, fontsize=12, rotation=45, ha="right", va="center")
            ax_diff.set_ylabel(test, fontsize=12, rotation=45, ha="right", va="center")

            # Add legends
            ax_size.legend(loc="upper right")
            ax_diff.legend(loc="upper right")

            # Add summary statistics
            summary = f"$\\mathbf{{Net:}}$  {data['total_diff']:+,d} bytes"
            if test in self.diff_functions and test in self.all_functions:
                summary += f" | $\\mathbf{{Changed:}}$  {self.diff_functions[test]} / {self.all_functions[test]} ({self.diff_functions[test] / self.all_functions[test] * 100:.2f}%) functions"
            else:
                summary += ""
            summary += f"\n$\\mathbf{{Min:}}$  {data['min_diff']:,d} @ {data['min_func'] if len(data['min_func']) <= 90 else data['min_func'][:90] + '...'}"
            summary += f"\n$\\mathbf{{Max:}}$  {data['max_diff']:,d} @ {data['max_func'] if len(data['max_func']) <= 90 else data['max_func'][:90] + '...'}"

            # Position text box in lower left corner for both plots
            ax_size.text(
                0.02,
                1.05,
                summary,
                transform=ax_size.transAxes,
                ha="left",
                va="bottom",
                fontsize=9,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.9, pad=0.6),
                multialignment="left",
                usetex=False,
            )
            ax_diff.text(
                0.02,
                1.05,
                summary,
                transform=ax_diff.transAxes,
                ha="left",
                va="bottom",
                fontsize=9,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.9, pad=0.6),
                multialignment="left",
                usetex=False,
            )

            # Grid
            ax_size.grid(
                True,
                which="both",
                axis="both",
                linestyle="dotted",
                color="#8B949E",
                alpha=0.7,
            )
            ax_diff.grid(
                True,
                which="both",
                axis="both",
                linestyle="dotted",
                color="#8B949E",
                alpha=0.7,
            )

            # Add vertical line at x=0 for difference plot
            ax_diff.axvline(x=0, color="black", linestyle="--", alpha=0.5)

        # Common x-axis labels
        axes_size[-1].set_xlabel("Function Size (bytes)", fontsize=12, color=BLACK)
        axes_diff[-1].set_xlabel("Size Difference (bytes)", fontsize=12, color=BLACK)

        # Adjust layout
        plt.figure(fig_size.number)
        plt.tight_layout()
        plt.figure(fig_diff.number)
        plt.tight_layout()

        # Save the figures
        plt.figure(fig_size.number)
        plt.savefig(plot_file_size)
        plt.figure(fig_diff.number)
        plt.savefig(plot_file_diff)
        plt.close("all")


if __name__ == "__main__":

    # User must supply results directory
    # Optionally, results can be merged across profiles
    parser = argparse.ArgumentParser(description="Convert results to CSV")
    parser.add_argument("results_dir", type=str, help="Results directory")
    parser.add_argument("test_profiles_dir", type=str, help="Test profiles directory")
    parser.add_argument("optimization_flag", type=str, help="Optimization flag")
    parser.add_argument(
        "-c", "--csv", action="store_true", help="Plot results from CSV"
    )
    parser.add_argument(
        "-m", "--merge", action="store_true", help="Merge results across profiles"
    )
    parser.add_argument(
        "-p", "--plot", action="store_true", help="Plot results using matplotlib"
    )
    args = parser.parse_args()

    # Check if the argument is a file
    results_dir = args.results_dir
    if not os.path.isdir(results_dir):
        print(f"Results directory {results_dir} does not exist!")
        exit(1)

    FLAG = args.optimization_flag.replace("-", "")

    CSV_PATH = results_dir + "/csv"
    RUNTIME_RESULTS_FILE = CSV_PATH + "/runtime-results.csv"
    COMPILE_TIME_RESULTS_FILE = CSV_PATH + "/compile-time-results.csv"
    OBJECT_SIZE_RESULTS_FILE = CSV_PATH + "/object-size-results.csv"
    MEMORY_USAGE_RESULTS_FILE = CSV_PATH + "/memory-usage-results.csv"
    ASM_SIZE_RESULTS_FILE = CSV_PATH + "/asm-size-results.csv"
    TEST_INFO_FILE = CSV_PATH + "/test-info.csv"

    # Create the csv directory if it does not exist already
    if not os.path.exists(CSV_PATH):
        os.makedirs(CSV_PATH)

    compile_time = CompileTimeResultsExtractor(results_dir)
    runtime = RuntimeResultsExtractor(results_dir)
    object_size = ObjectSizeResultsExtractor(results_dir)
    memory_usage = MemoryUsageResultsExtractor(results_dir)
    asm_size = AsmSizeResultsExtractor(results_dir)
    test_info = TestInfoExtractor(results_dir, args.test_profiles_dir)

    if not args.csv:
        compile_time.write_results(COMPILE_TIME_RESULTS_FILE)
        runtime.write_results(RUNTIME_RESULTS_FILE)
        object_size.write_results(OBJECT_SIZE_RESULTS_FILE)
        memory_usage.write_results(MEMORY_USAGE_RESULTS_FILE)
        asm_size.write_results(ASM_SIZE_RESULTS_FILE)
        test_info.write_results(TEST_INFO_FILE)
    else:
        for results_file in [
            COMPILE_TIME_RESULTS_FILE,
            RUNTIME_RESULTS_FILE,
            OBJECT_SIZE_RESULTS_FILE,
            ASM_SIZE_RESULTS_FILE,
        ]:
            if not os.path.exists(results_file):
                print(f"Results file {results_file} does not exist!")
                exit(1)

    if args.plot:
        PLOT_PATH = results_dir + "/plots"
        if not os.path.exists(PLOT_PATH):
            os.makedirs(PLOT_PATH)

        compile_time.plot_results(COMPILE_TIME_RESULTS_FILE, PLOT_PATH)
        runtime.plot_results(RUNTIME_RESULTS_FILE, PLOT_PATH)
        object_size.plot_results(OBJECT_SIZE_RESULTS_FILE, PLOT_PATH)
        memory_usage.plot_results(MEMORY_USAGE_RESULTS_FILE, PLOT_PATH)
        asm_size.plot_results(ASM_SIZE_RESULTS_FILE, PLOT_PATH)

    if args.merge:
        compile_time.merge_results(COMPILE_TIME_RESULTS_FILE)
        runtime.merge_results(RUNTIME_RESULTS_FILE)
        object_size.merge_results(OBJECT_SIZE_RESULTS_FILE)
        memory_usage.merge_results(MEMORY_USAGE_RESULTS_FILE)
