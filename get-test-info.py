import csv
import sys
import os
import xml.etree.ElementTree as ET
import argparse
from tabulate import tabulate


class Writer:
    def __init__(self):
        pass

    def write(self, test_info):
        pass


class MarkdownWriter(Writer):
    def write(self, test_info):
        headers = ["Name", "Version", "Description"]
        rows = [
            [info["name"], info["version"], info["description"]] for info in test_info
        ]

        sys.stdout.write("# Test Profiles\n\n")
        sys.stdout.write(tabulate(rows, headers, tablefmt="pipe"))
        sys.stdout.write("\n")


class CSVWriter(Writer):
    def write(self, test_info):
        writer = csv.DictWriter(
            sys.stdout, fieldnames=["name", "version", "description"]
        )
        writer.writeheader()
        writer.writerows(test_info)


def parse_test_profile(test_name, path):
    tree = ET.parse(path)
    root = tree.getroot()

    test_name = test_name.split("/")[1].rsplit("-", 1)[0]

    return {
        "name": test_name,
        "version": root.find(".//AppVersion").text,
        "description": root.find(".//Description").text,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract test information")
    parser.add_argument(
        "test_profiles_dir", type=str, help="Path to test-profiles directory"
    )
    parser.add_argument(
        "test_names_file", type=str, help="Path to a file containing test names"
    )
    parser.add_argument(
        "--output-format",
        type=str,
        choices=["markdown", "csv"],
        default="markdown",
        help="Output format",
    )
    args = parser.parse_args()

    if not os.path.exists(args.test_profiles_dir):
        print(f"Test profiles directory {args.test_profiles_dir} does not exist!")
        exit(1)
    if not os.path.exists(args.test_names_file):
        print(f"Test names file {args.test_names_file} does not exist!")
        exit(1)

    with open(args.test_names_file, "r") as f:
        test_names_file = [line.strip() for line in f.readlines()]

    test_info = []
    for test_name in test_names_file:
        path = os.path.join(args.test_profiles_dir, test_name, "test-definition.xml")
        test_info += [parse_test_profile(test_name, path)]

    if args.output_format == "markdown":
        writer = MarkdownWriter()
    elif args.output_format == "csv":
        writer = CSVWriter()
    writer.write(test_info)
