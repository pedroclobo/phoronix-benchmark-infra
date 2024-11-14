import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
import xml.etree.ElementTree as ET
import argparse
from matplotlib.ticker import AutoMinorLocator

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
            for profile in os.listdir(self.results_dir + "/test-results/" + test):
                profile_path = os.path.join(
                    self.results_dir + "/test-results", test, profile, "composite.xml"
                )
                tree = ET.parse(profile_path)
                root = tree.getroot()

                for result in root.findall(".//Result"):
                    title = result.find("Identifier").text
                    description = result.find("Description").text or "No description"
                    scale = result.find("Scale").text
                    proportion = result.find("Proportion").text
                    for entry in result.findall(".//Data/Entry"):
                        profile = entry.find("Identifier").text
                        value = entry.find("Value").text or float("nan")
                        self.results.append(
                            (title, description, scale, proportion, profile, value)
                        )

        self.results.sort(key=lambda x: (x[0], x[4], x[1]))

    def write_results(self, results_file):
        print(f"Writing runtime results to {results_file}")
        with open(results_file, "w") as f:
            f.write("Test;Description;Scale;Proportion;Profile;Value\n")
            for test, description, scale, proportion, profile, value in self.results:
                f.write(
                    f"{test};{description};{scale};{proportion};{profile};{value}\n"
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

        # Read data and remove test version
        df = pd.read_csv(results_file, sep=";")
        df["Test"] = df["Test"].apply(
            lambda x: "-".join(x.split("/", 1)[1].split("-")[:-1])
        )

        _, ax = plt.subplots(figsize=(8, 6))
        ax.set_facecolor(BACKGROUND)

        # Pivot the data and sort by Test
        df = df.pivot_table(
            index=("Test", "Description", "Scale", "Proportion"),
            columns="Profile",
            values="Value",
        ).reset_index()
        df.sort_values(by="Test", ascending=False, inplace=True)

        df_percentage = pd.Series(
            np.where(
                df["Proportion"] == "HIB",
                (df["base"] - df["byte"]) / df["byte"] * 100,
                (df["byte"] - df["base"]) / df["base"] * 100,
            ),
            index=df.index,
        )

        df["Percentage"] = df_percentage

        # Group by Test and calculate the average percentage regression
        avg_percentage = df.groupby("Test")["Percentage"].mean().reset_index()
        avg_percentage.set_index("Test", inplace=True)
        avg_percentage.sort_values(by="Test", inplace=True, ascending=False)
        avg_percentage["Percentage"] = avg_percentage["Percentage"].astype(float)

        colors = []
        for percentage in avg_percentage["Percentage"]:
            colors.append(GREEN if percentage < 0 else RED)

        avg_percentage["Percentage"].plot(kind="barh", ax=ax, color=colors, width=0.8)

        ax.set(ylabel=None)
        plt.xlabel(
            "Runtime regression relative to baseline (%)", fontsize=12, color="#24292F"
        )

        # Prevent annotations from going outside the plot
        min_percentage = avg_percentage.min().min()
        max_percentage = avg_percentage.max().max()
        ax.set_xlim(min_percentage * 1.05, max(max_percentage * 1.05, 0.5))

        ax.grid(
            True,
            which="both",
            axis="x",
            linestyle="dotted",
            color="#8B949E",
            alpha=0.7,
        )

        ax.axvline(x=0, color="black", linestyle="dotted", linewidth=0.9)
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
                profile_path = os.path.join(
                    self.results_dir + "/compile-time", test, profile
                )
                with open(profile_path, "r") as f:
                    self.results += [(test, profile, sum([int(line) for line in f]))]

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

        # Read data, remove test version and convert compile time to seconds
        df = pd.read_csv(results_file, sep=";")
        df["Test"] = df["Test"].apply(lambda x: "-".join(x.split("-")[:-1]))
        df["Compile Time"] = df["Compile Time"] / 1000

        _, ax = plt.subplots(figsize=(8, 6))
        ax.set_facecolor(BACKGROUND)
        df = df.pivot_table(index="Test", columns="Profile", values="Compile Time")
        df.sort_values(by="Test", ascending=False, inplace=True)
        df.plot(kind="barh", ax=ax, color=[BLUE, RED], width=0.7)

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
                if percentage_change == 0.0:
                    percentage_change *= percentage_change
                change_text = f"{percentage_change:.2f}%"
            else:
                change_text = "nan%"

            x_min, x_max = ax.get_xlim()
            ax.text(
                max(base_value, byte_value) + 0.04 * (x_max - x_min),
                i - 0.1,
                change_text,
                ha="center",
                color=(
                    BRIGHTRED
                    if percentage_change > 0
                    else BRIGHTGREEN if percentage_change < 0 else BRIGHTYELLOW
                ),
                fontsize=10,
                fontweight="bold",
            )

        ax.legend(
            title="Profile",
            loc="lower right",
            fontsize=12,
            title_fontsize=14,
            frameon=True,
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
                    self.results_dir + "/object-size", test, profile
                )
                with open(profile_path, "r") as f:
                    sum = 0
                    for line in f:
                        # File output has a tab
                        if (len(line.split("\t"))) != 3:
                            continue
                        size, _, type = line.split("\t")
                        if "ELF" in type:
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

        # Read data, remove test version and convert object size to MB
        df = pd.read_csv(results_file, sep=";")
        df["Test"] = df["Test"].apply(lambda x: "-".join(x.split("-")[:-1]))
        df["Size"] = df["Size"] / (1024 * 1024)

        _, ax = plt.subplots(figsize=(8, 6))
        ax.set_facecolor(BACKGROUND)
        df = df.pivot_table(index="Test", columns="Profile", values="Size")
        df.sort_values(by="Test", ascending=False, inplace=True)
        df.plot(kind="barh", ax=ax, color=[BLUE, RED], width=0.7)

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
                if percentage_change == 0.0:
                    percentage_change *= percentage_change
                change_text = f"{percentage_change:.2f}%"
            else:
                change_text = "nan%"

            x_min, x_max = ax.get_xlim()
            ax.text(
                max(base_value, byte_value) + 0.04 * (x_max - x_min),
                i - 0.1,
                change_text,
                ha="center",
                color=(
                    BRIGHTRED
                    if percentage_change > 0
                    else BRIGHTGREEN if percentage_change < 0 else BRIGHTYELLOW
                ),
                fontsize=10,
                fontweight="bold",
            )

        ax.legend(
            title="Profile",
            loc="lower right",
            fontsize=12,
            title_fontsize=14,
            frameon=True,
        )

        plt.subplots_adjust(bottom=0.1, top=0.99, left=0.15, right=0.98)
        plt.savefig(plot_file)
        plt.close()


class MemoryUsageResultsExtractor(ResultsExtractor):
    def compute_results(self):
        self.results = []
        for test in os.listdir(self.results_dir + "/memory-usage"):
            for profile in os.listdir(self.results_dir + "/memory-usage/" + test):
                profile_path = os.path.join(
                    self.results_dir + "/memory-usage", test, profile
                )
                maximum = 0
                with open(profile_path, "r") as f:
                    for line in f:
                        if "Maximum resident set size" in line:
                            maximum = max(maximum, int(line.split(":")[1]))

                self.results += [(test, profile, maximum)]

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

        # Read data and remove test version
        df = pd.read_csv(results_file, sep=";")
        df["Test"] = df["Test"].apply(lambda x: "-".join(x.split("-")[:-1]))

        _, ax = plt.subplots(figsize=(8, 6))
        ax.set_facecolor(BACKGROUND)
        df = df.pivot_table(index="Test", columns="Profile", values="Peak Memory Usage")
        df.sort_values(by="Test", ascending=False, inplace=True)
        df.plot(kind="barh", ax=ax, color=[BLUE, RED], width=0.7)

        ax.set(ylabel=None)
        plt.xlabel("Peak memory usage (kB)", fontsize=12, color=BLACK)

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
                if percentage_change == 0.0:
                    percentage_change *= percentage_change
                change_text = f"{percentage_change:.2f}%"
            else:
                change_text = "nan%"

            x_min, x_max = ax.get_xlim()
            ax.text(
                max(base_value, byte_value) + 0.04 * (x_max - x_min),
                i - 0.1,
                change_text,
                ha="center",
                color=(
                    BRIGHTRED
                    if percentage_change > 0
                    else BRIGHTGREEN if percentage_change < 0 else BRIGHTYELLOW
                ),
                fontsize=10,
                fontweight="bold",
            )

        ax.legend(
            title="Profile",
            loc="lower right",
            fontsize=12,
            title_fontsize=14,
            frameon=True,
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
                self.results_dir + "/object-size", test, profile
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
                    args.test_profiles_dir, "pts", test, "test-definition.xml"
                ),
                "r",
            ) as f:
                tree = ET.parse(f)
                root = tree.getroot()

                test_name = test.rsplit("-", 1)[0]
                version = root.find(".//AppVersion").text
                description = root.find(".//Description").text

            self.results += [(test_name, version, description, loc)]

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


if __name__ == "__main__":

    # User must supply results directory
    # Optionally, results can be merged across profiles
    parser = argparse.ArgumentParser(description="Convert results to CSV")
    parser.add_argument("results_dir", type=str, help="Results directory")
    parser.add_argument("test_profiles_dir", type=str, help="Test profiles directory")
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

    CSV_PATH = results_dir + "/csv"
    RUNTIME_RESULTS_FILE = CSV_PATH + "/runtime-results.csv"
    COMPILE_TIME_RESULTS_FILE = CSV_PATH + "/compile-time-results.csv"
    OBJECT_SIZE_RESULTS_FILE = CSV_PATH + "/object-size-results.csv"
    MEMORY_USAGE_RESULTS_FILE = CSV_PATH + "/memory-usage-results.csv"
    TEST_INFO_FILE = CSV_PATH + "/test-info.csv"

    # Create the csv directory if it does not exist already
    if not os.path.exists(CSV_PATH):
        os.makedirs(CSV_PATH)

    compile_time = CompileTimeResultsExtractor(results_dir)
    runtime = RuntimeResultsExtractor(results_dir)
    object_size = ObjectSizeResultsExtractor(results_dir)
    memory_usage = MemoryUsageResultsExtractor(results_dir)
    test_info = TestInfoExtractor(results_dir, args.test_profiles_dir)

    if not args.csv:
        compile_time.write_results(COMPILE_TIME_RESULTS_FILE)
        runtime.write_results(RUNTIME_RESULTS_FILE)
        object_size.write_results(OBJECT_SIZE_RESULTS_FILE)
        memory_usage.write_results(MEMORY_USAGE_RESULTS_FILE)
        test_info.write_results(TEST_INFO_FILE)
    else:
        for results_file in [
            COMPILE_TIME_RESULTS_FILE,
            RUNTIME_RESULTS_FILE,
            OBJECT_SIZE_RESULTS_FILE,
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

    if args.merge:
        compile_time.merge_results(COMPILE_TIME_RESULTS_FILE)
        runtime.merge_results(RUNTIME_RESULTS_FILE)
        object_size.merge_results(OBJECT_SIZE_RESULTS_FILE)
        memory_usage.merge_results(MEMORY_USAGE_RESULTS_FILE)
