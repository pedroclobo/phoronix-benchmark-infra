#!/bin/bash

# Function to display usage
usage() {
    echo "Usage: $0 [options] <config_file>"
    echo "Options:"
    echo "  -p, --prepare   Tweak environement to decrease result variance (needs sudo)"
    echo "  -h, --help      Display this message"
    exit 1
}

# Default behavior
run_prepare=0

# Parse command line arguments
TEMP=$(getopt -o ph --long prepare,help -n "$0" -- "$@")
if [ $? != 0 ] ; then echo "Termination..." >&2 ; exit 1 ; fi
eval set -- "$TEMP"

while true; do
    case "$1" in
        -p | --prepare)
            run_prepare=1
            shift
        ;;
        -h | --help)
            usage
        ;;
        -- )
            shift
            break
        ;;
        * )
            break
        ;;
    esac
done

# Ensure config file is provided
[ $# -ne 1 ] && usage
config_file="$1"

# Config file must exist
[ ! -f "$config_file" ] && echo "Configuration file does not exist!" && exit 1

# Parse the config file
export CONFIG_NAME=$(jq -r '.CONFIG_NAME' "$config_file")
export PTS_BASE=$(jq -r '.PTS_BASE' "$config_file")
export TEST_PROFILES_PATH=$(jq -r '.TEST_PROFILES_PATH' "$config_file")
export TOOLCHAIN_PATH=$(jq -r '.TOOLCHAIN_PATH' "$config_file")
export LLVM_PATH=$(jq -r '.LLVM_PATH' "$config_file")
export FLAGS=$(jq -r '.FLAGS' "$config_file")
export RESULTS_PATH=$(jq -r '.RESULTS_PATH' "$config_file")
export PROFILES_FILE=$(jq -r '.PROFILES_FILE' "$config_file")
export NUM_CPU_CORES=$(jq -r '.NUM_CPU_CORES' "$config_file")
export PIN_CMD=$(jq -r '.PIN_CMD' "$config_file")

# Verify the paths
[ ! -d $PTS_BASE ] && echo "PTS not found!" && exit 1
[ ! -d $TEST_PROFILES_PATH ] && echo "Test profiles not found!" && exit 1
[ ! -d $TOOLCHAIN_PATH ] && echo "Toolchain not found!" && exit 1
[ ! -d $LLVM_PATH ] && echo "LLVM not found!" && exit 1
[ ! -d $RESULTS_PATH ] && mkdir $RESULTS_PATH
[ ! -f $PROFILES_FILE ] && echo "Profiles file does not exist!" && exit 1

# Phoronix test suite command
export PTS="$PTS_BASE/phoronix-test-suite"

# Export the profile name to be used as a identifier in phoronix
export TEST_RESULTS_IDENTIFIER=$CONFIG_NAME

# Delete previously installed tests and results
rm -rf $RESULTS_PATH/installed-tests/*
rm -rf $RESULTS_PATH/test-results/*
rm -rf $RESULTS_PATH/object-size/*
rm -rf $RESULTS_PATH/compile-time/*
rm -rf $RESULTS_PATH/memory-usage/*

# Create directory for compile time, object size and memory usage results
[ ! -d $RESULTS_PATH/object-size ] && mkdir $RESULTS_PATH/object-size
[ ! -d $RESULTS_PATH/compile-time ] && mkdir $RESULTS_PATH/compile-time
[ ! -d $RESULTS_PATH/memory-usage ] && mkdir $RESULTS_PATH/memory-usage

# Prepare environement to decrease result variance (needs sudo)
[[ $run_prepare -eq 1 ]] && ./prepare-benchmark-env.sh 1

# Point to the toolchain wrappers
export CC=$TOOLCHAIN_PATH/clang
export CXX=$TOOLCHAIN_PATH/clang++

# Set compiler flags
export CFLAGS=$FLAGS
export CXXFLAGS=$FLAGS

# Generate phoronix user configuration
batch_setup=$(
	# Save test results when in batch mode
	echo y && \
	# Open the web browser automatically when in batch mode
	echo n && \
	# Auto upload the results to OpenBenchmarking.org
	echo y && \
	# Prompt for test identifier
	echo n && \
	# Prompt for test description
	echo n && \
	# Prompt for saved results file-name
	echo n && \
	# Run all test options
	echo y
)
echo $batch_setup | $PTS batch-setup

for p in $(grep -v '#' $PROFILES_FILE); do
	# Export basename variable, used to measure compile time in toolchain/
	export basename=$(basename $p)

	# Install and measure compile time and memory usage
	$PTS batch-install $p

	# Measure object size
	SIZE_DIR=$RESULTS_PATH/object-size/$(echo $p | cut -d'/' -f2)
	[ ! -d $SIZE_DIR ] && mkdir -p $SIZE_DIR
	du -ab $RESULTS_PATH/installed-tests/$p | while read size file; do
		echo -e "$size\t$file\t$(file -b "$file")"
	done > $SIZE_DIR/$CONFIG_NAME

	# Run the test
	result_name=`echo $p | cut -d'/' -f2`"_"
	echo -n $result_name | $PTS batch-run $p
done

rm -rf $RESULTS_PATH/installed-tests/*
