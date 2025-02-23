# Phoronix Benchmark Infrastructure

This repository contains scripts and configurations to automate benchmarking of the Clang compiler using the Phoronix Test Suite. The benchmarked metrics include compile time, (peak) memory usage, object size and execution time.

## Setup

Clone the necessary repositories and create symbolic links:

```sh
git clone https://github.com/phoronix-test-suite/phoronix-test-suite.git
git clone https://github.com/pedroclobo/test-profiles.git --branch=clang
mkdir ~/.phoronix-test-suite
ln -s ~/test-profiles ~/.phoronix-test-suite/test-profiles
```

## Configuration

Configuration profiles are located in the `config/` directory.
Each configuration file is a JSON file that specifies paths and settings for the benchmarks.

- `CONFIG_NAME`: Name of the configuration.
- `LLVM_PATH`: Path to the LLVM `bin` directory.
- `FLAGS`: Clang flags.
- `PTS_BASE`: Path to the Phoronix Test Suite repository (cloned in the setup step).
- `TEST_PROFILES_PATH`: Path to the test profiles repository (cloned in the setup step).
- `TOOLCHAIN_PATH`: Path to the toolchain scripts (located in the `toolchain/` directory).
- `RESULTS_PATH`: Path to install the programs and store the results of the benchmarks.
- `PROFILES_FILE`: Path to the profiles file containing the tests to run.
- `NUM_CPU_CORES`: Number of CPU cores to use (both during compilation and benchmarking).

```json
{
  "CONFIG_NAME": "baseline",
  "LLVM_PATH": "/home/user/llvm/build/bin",
  "FLAGS": "-O2",
  "PTS_BASE": "/home/user/phoronix-test-suite",
  "TEST_PROFILES_PATH": "/home/user/test-profiles",
  "TOOLCHAIN_PATH": "/home/user/phoronix-benchmark-infra/toolchain",
  "RESULTS_PATH": "/home/user/.phoronix-test-suite",
  "PROFILES_FILE": "/home/user/phoronix-benchmark-infra/profiles.txt",
  "NUM_CPU_CORES": 16
}
```

## Test Profiles

Custom test profiles are used to ensure compatiblity with the Clang compiler.
These are available [here](https://github.com/pedroclobo/test-profiles.git/tree/clang), under the `local` folder.

The following is an example of a `profiles.txt` file:

```
local/aircrack-ng
local/botan
local/compress-pbzip2
local/compress-zstd
local/crafty
local/draco
local/espeak
local/fftw
local/graphics-magick
local/john-the-ripper
local/luajit
local/ngspice
local/openssl
local/primesieve
local/rnnoise
local/scimark2
local/sqlite-speedtest
local/tjbench
local/z3
```

## Running Benchmarks

### Single Configuration

To run the tests specified in `profiles.txt` for a single configuration, use the `run.sh` script:

```sh
# -p will prepare the environment to decrease result variance (requires sudo)
./run.sh -p config/base.json
```

### All Configurations

To run all configurations in a directory, generating the plots and uploading the results to GitHub, use the `run-all.sh` script:

```sh
./run-all.sh -p config/ /path/to/results/repo profiles.txt
```

**Make sure to previously set up the repository as the script will push the results to the remote.**


## Extracting Results

Use the `results-to-csv.py` script to convert results to CSV format and generate plots:

```sh
python3 results-to-csv.py /path/to/results /path/to/test-profiles -mp
```

## Gathering Test Information

Use the `get-test-info.py` script to extract test information from the test profiles:

```sh
python3 get-test-info.py /path/to/test-profiles profiles.txt --output-format markdown
```

## Toolchain

Custom toolchains are located in the `toolchain/` directory.
The `clang` and `clang++` scripts wrap the LLVM compilers to remove blacklisted flags and measure compile time and memory usage.

**The script override the default optimization level as most makefiles override these flags.
Make sure to update the script if needing to benchmark with an optimzation level different from `-O2`.**
