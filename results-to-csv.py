import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
import xml.etree.ElementTree as ET
import argparse
from matplotlib.ticker import AutoMinorLocator


def get_runtime_results(results_dir):
    results = []

    for test in os.listdir(results_dir + "/test-results"):
        for profile in os.listdir(results_dir + "/test-results/" + test):
            profile_path = os.path.join(
                results_dir + "/test-results", test, profile, "composite.xml"
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
                    results.append(
                        (title, description, scale, proportion, profile, value)
                    )

    results.sort(key=lambda x: (x[0], x[4], x[1]))

    return results


def get_compile_time_results(results_dir):
    results = []

    for test in os.listdir(results_dir + "/compile-time"):
        for profile in os.listdir(results_dir + "/compile-time/" + test):
            profile_path = os.path.join(results_dir + "/compile-time", test, profile)
            with open(profile_path, "r") as f:
                results += [(test, profile, sum([int(line) for line in f]))]

    results.sort(key=lambda x: (x[0], x[1]))

    return results


def get_object_size_results(results_dir):
    results = []

    for test in os.listdir(results_dir + "/object-size"):
        for profile in os.listdir(results_dir + "/object-size/" + test):
            profile_path = os.path.join(results_dir + "/object-size", test, profile)
            with open(profile_path, "r") as f:
                sum = 0
                for line in f:
                    # File output has a tab
                    if (len(line.split("\t"))) != 3:
                        continue
                    size, _, type = line.split("\t")
                    if "ELF" in type:
                        sum += int(size)
                results += [(test, profile, sum)]

    results.sort(key=lambda x: (x[0], x[1]))

    return results


def write_compile_time_results(results, results_file):
    print(f"Writing compile time results to {results_file}")
    with open(results_file, "w") as f:
        f.write("Test;Profile;Compile Time\n")
        for test, profile, total in results:
            f.write(f"{test};{profile};{total}\n")


def write_runtime_results(results, results_file):
    print(f"Writing runtime time results to {results_file}")
    with open(results_file, "w") as f:
        f.write("Test;Description;Scale;Proportion;Profile;Value\n")
        for test, description, scale, proportion, profile, value in results:
            f.write(f"{test};{description};{scale};{proportion};{profile};{value}\n")


def write_object_size_results(results, results_file):
    print(f"Writing object size results to {results_file}")
    with open(results_file, "w") as f:
        f.write("Test;Profile;Size\n")
        for test, profile, size in results:
            f.write(f"{test};{profile};{size}\n")


def merge_compile_time_results(results_file):
    df = pd.read_csv(results_file, sep=";")
    pivot_table = df.pivot_table(
        index=["Test"],
        columns="Profile",
        values="Compile Time",
    )
    pivot_table.to_csv(results_file, sep=";")


def merge_runtime_results(results_file):
    df = pd.read_csv(results_file, sep=";")
    pivot_table = df.pivot_table(
        index=["Test", "Description", "Scale", "Proportion"],
        columns="Profile",
        values="Value",
    )
    pivot_table.to_csv(results_file, sep=";")


def merge_object_size_results(results_file):
    df = pd.read_csv(results_file, sep=";")
    pivot_table = df.pivot_table(
        index=["Test"],
        columns="Profile",
        values="Size",
    )
    pivot_table.to_csv(results_file, sep=";")


def plot_compile_time_results(results_file, plot_dir):
    plot_file = f"{plot_dir}/compile-time.png"
    print(f"Plotting compile time results to {plot_file}")

    # Read data, remove test version and convert compile time to seconds
    df = pd.read_csv(results_file, sep=";")
    df["Test"] = df["Test"].apply(lambda x: "-".join(x.split("-")[:-1]))
    df["Compile Time"] = df["Compile Time"] / 1000

    _, ax = plt.subplots(figsize=(10, 6))
    ax.set_facecolor("#F6F8FA")
    df = df.pivot_table(index="Test", columns="Profile", values="Compile Time")
    df.plot(kind="bar", ax=ax, color=["#0969DA", "#FF8C00"], width=0.7)

    ax.set(xlabel=None)
    plt.ylabel("Time (sec)", fontsize=12, color="#24292F")

    # Prevent annotations from going outside the plot
    max_value = df.max().max()
    ax.set_ylim(1, max_value + 80)

    # Tilt x-axis labels for better readability
    plt.xticks(rotation=45, ha="right", fontsize=11, color="#24292F")

    ax.grid(
        True,
        which="both",
        axis="y",
        linestyle="dotted",
        color="#8B949E",
        alpha=0.7,
    )

    # Annotate plots with regression percentage
    for i, test in enumerate(df.index):
        base_value = df.loc[test, "base"]
        byte_value = df.loc[test, "byte"]

        if not np.isnan(base_value):
            percentage_change = round(((byte_value - base_value) / base_value) * 100, 1)
            if percentage_change == 0.0:
                percentage_change *= percentage_change
            change_text = f"{percentage_change:.1f}%"
        else:
            change_text = "nan%"

        mid_x = i
        ax.text(
            mid_x,
            max(1.5, max(base_value, byte_value) + 20),
            change_text,
            ha="center",
            color=(
                "#CF222E"
                if percentage_change > 0
                else "#116329" if percentage_change < 0 else "#B08800"
            ),
            fontsize=10,
            fontweight="bold",
        )

    ax.legend(
        title="Profile",
        loc="upper right",
        fontsize=12,
        title_fontsize=14,
        frameon=True,
    )

    plt.subplots_adjust(bottom=0.2, top=0.98, left=0.085, right=0.98)
    plt.savefig(plot_file, dpi=300)
    plt.close()


def plot_runtime_results(results_file, plot_dir):
    plot_file = f"{plot_dir}/runtime.png"
    print(f"Plotting runtime results to {plot_file}")

    # Read data and remove test version
    df = pd.read_csv(results_file, sep=";")
    df["Test"] = df["Test"].apply(
        lambda x: "-".join(x.split("/", 1)[1].split("-")[:-1])
    )

    _, ax = plt.subplots(figsize=(10, 6))
    ax.set_facecolor("#F6F8FA")

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
        colors.append("#CF222E" if percentage < 0 else "#116329")

    avg_percentage["Percentage"].plot(kind="barh", ax=ax, color=colors, width=0.8)

    ax.set(ylabel=None)
    plt.xlabel("Improvement Relative to Baseline (%)", fontsize=12, color="#24292F")

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

    plt.subplots_adjust(bottom=0.1, top=0.99, left=0.12, right=0.98)
    plt.savefig(plot_file, dpi=300)
    plt.close()


def plot_object_size_results(results_file, plot_dir):
    plot_file = f"{plot_dir}/object-size.png"
    print(f"Plotting object size results to {plot_file}")

    # Read data, remove test version and convert object size to MB
    df = pd.read_csv(results_file, sep=";")
    df["Test"] = df["Test"].apply(lambda x: "-".join(x.split("-")[:-1]))
    df["Size"] = df["Size"] / (1024 * 1024)

    _, ax = plt.subplots(figsize=(10, 6))
    ax.set_facecolor("#F6F8FA")
    df = df.pivot_table(index="Test", columns="Profile", values="Size")
    df.plot(kind="bar", ax=ax, color=["#0969DA", "#FF8C00"], width=0.7)

    ax.set(xlabel=None)
    plt.ylabel("Size (MB)", fontsize=12, color="#24292F")

    # Prevent annotations from going outside the plot
    max_value = df.max().max()
    ax.set_ylim(1, max_value * 1.05)

    # Tilt x-axis labels for better readability
    plt.xticks(rotation=45, ha="right", fontsize=11, color="#24292F")

    ax.grid(
        True,
        which="both",
        axis="y",
        linestyle="dotted",
        color="#8B949E",
        alpha=0.7,
    )

    # Annotate plots with regression percentage
    for i, test in enumerate(df.index):
        base_value = df.loc[test, "base"]
        byte_value = df.loc[test, "byte"]

        if not np.isnan(base_value):
            percentage_change = round(((byte_value - base_value) / base_value) * 100, 1)
            if percentage_change == 0.0:
                percentage_change *= percentage_change
            change_text = f"{percentage_change:.1f}%"
        else:
            change_text = "nan%"

        mid_x = i
        ax.text(
            mid_x,
            max(1.5, max(base_value, byte_value) + 0.5),
            change_text,
            ha="center",
            color=(
                "#CF222E"
                if percentage_change > 0
                else "#116329" if percentage_change < 0 else "#B08800"
            ),
            fontsize=10,
            fontweight="bold",
        )

    ax.legend(
        title="Profile",
        loc="upper right",
        fontsize=12,
        title_fontsize=14,
        frameon=True,
    )

    plt.subplots_adjust(bottom=0.2, top=0.98, left=0.07, right=0.98)
    plt.savefig(plot_file, dpi=300)
    plt.close()


if __name__ == "__main__":

    # User must supply results directory
    # Optionally, results can be merged across profiles
    parser = argparse.ArgumentParser(description="Convert results to CSV")
    parser.add_argument("results_dir", type=str, help="Results directory")
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

    # Create the csv directory if it does not exist already
    if not os.path.exists(CSV_PATH):
        os.makedirs(CSV_PATH)

    if not args.csv:
        write_compile_time_results(
            get_compile_time_results(results_dir), COMPILE_TIME_RESULTS_FILE
        )
        write_runtime_results(get_runtime_results(results_dir), RUNTIME_RESULTS_FILE)
        write_object_size_results(
            get_object_size_results(results_dir), OBJECT_SIZE_RESULTS_FILE
        )
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

        plot_compile_time_results(COMPILE_TIME_RESULTS_FILE, PLOT_PATH)
        plot_runtime_results(RUNTIME_RESULTS_FILE, PLOT_PATH)
        plot_object_size_results(OBJECT_SIZE_RESULTS_FILE, PLOT_PATH)

    if args.merge:
        merge_compile_time_results(COMPILE_TIME_RESULTS_FILE)
        merge_runtime_results(RUNTIME_RESULTS_FILE)
        merge_object_size_results(OBJECT_SIZE_RESULTS_FILE)
