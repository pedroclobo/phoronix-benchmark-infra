#!/bin/bash -ex

# User must provide a config file
[ $# -ne 1 ] && echo "Usage: $0 <config>" && exit 1

# Config file must exist
[ ! -f "$1" ] && echo "Configuration files does not exist!" && exit 1

# Parse the config file
config_file="$1"
export CONFIG_NAME=$(jq -r '.CONFIG_NAME' "$config_file")
export PTS_BASE=$(jq -r '.PTS_BASE' "$config_file")
export TEST_PROFILES_PATH=$(jq -r '.TEST_PROFILES_PATH' "$config_file")
export TOOLCHAIN_PATH=$(jq -r '.TOOLCHAIN_PATH' "$config_file")
export LLVM_PATH=$(jq -r '.LLVM_PATH' "$config_file")
export FLAGS=$(jq -r '.FLAGS' "$config_file")
export RESULTS_PATH=$(jq -r '.RESULTS_PATH' "$config_file")
export PROFILES_FILE=$(jq -r '.PROFILES_FILE' "$config_file")
export NUM_CPU_CORES=$(jq -r '.NUM_CPU_CORES' "$config_file")

# Verify the paths
[ ! -d $PTS_BASE ] && echo "PTS not found!" && exit 1
[ ! -d $TEST_PROFILES_PATH ] && echo "Test profiles not found!" && exit 1
[ ! -d $TOOLCHAIN_PATH ] && echo "Toolchain not found!" && exit 1
[ ! -d $LLVM_PATH ] && echo "LLVM not found!" && exit 1
[ ! -d $RESULTS_PATH ] && mkdir $RESULTS_PATH
[ ! -f $PROFILES_FILE ] && echo "Profiles file does not exist!" && exit 1

# Phoronix test suite command
export PTS="php $PTS_BASE/pts-core/phoronix-test-suite.php"

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

./prepare-benchmark-env.sh 1

# Point to the toolchain wrappers
export CC=$TOOLCHAIN_PATH/clang
export CXX=$TOOLCHAIN_PATH/clang++

for p in $(grep -v '#' $PROFILES_FILE); do
	# Export basename variable, used to measure compile time in toolchain/
	export basename=$(basename $p)

	# Install and measure compile time and memory usage
	$PTS debug-install $p

	# Measure object size
	SIZE_DIR=$RESULTS_PATH/object-size/$(echo $p | cut -d'/' -f2)
	[ ! -d $SIZE_DIR ] && mkdir -p $SIZE_DIR
	du -ab $RESULTS_PATH/installed-tests/$p | while read size file; do
		echo -e "$size\t$file\t$(file -b "$file")"
	done > $SIZE_DIR/$CONFIG_NAME

	batch_setup=$(echo y && echo n && echo n && echo y && echo n && echo y && echo y)
	echo $batch_setup | $PTS batch-setup

	# Run the test
	result_name=`echo $p | cut -d'/' -f2`"_"
	pts_command="echo -n '$result_name' | $PTS batch-run $p"
	sh -c "$pts_command" 2>&1
done

rm -rf $RESULTS_PATH/installed-tests/*
