#!/bin/bash

# Function to display usage
usage() {
    echo "Usage: $0 [options] <config_dir> <results_repo> <profiles_file>"
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

# Ensure config directory is provided
[ $# -ne 3 ] && usage
CONFIG_DIR="$1"
RESULTS_REPO="$2"
PROFILES_FILE="$3"

# Config directory must exist
[ ! -d "$CONFIG_DIR" ] && echo "Configuration file does not exist!" && exit 1

# Config directory must not be empty
[ ! "$(ls -A $CONFIG_DIR | grep .json)" ] && \
  echo "Configuration directory is empty!" && exit 1

# Results repository must exist
[ ! -d "$RESULTS_REPO" ] && echo "Results repository does not exist!" && exit 1
[ ! -d "$RESULTS_REPO/.git" ] && \
  echo "Results repository is not a git repository!" && exit 1

# Prepare environement to decrease result variance (needs sudo)
[[ $run_prepare -eq 1 ]] && ./prepare-benchmark-env.sh 1

# Create new branch in results repo
pushd $RESULTS_REPO
DATE=$(date +%Y-%m-%d-%H-%M-%S)
FORMATTED_DATE=$(date +"%d %B %Y - %H:%M")
git checkout --orphan $DATE-$(hostname)
git rm -rf .
git clean -df
popd

for p in $(grep -v '#' $PROFILES_FILE); do
    for c in $(ls $CONFIG_DIR/*.json); do
        # Parse the config file
        export CONFIG_NAME=$(jq -r '.CONFIG_NAME' "$c")
        export PTS_BASE=$(jq -r '.PTS_BASE' "$c")
        export TEST_PROFILES_PATH=$(jq -r '.TEST_PROFILES_PATH' "$c")
        export TOOLCHAIN_PATH=$(jq -r '.TOOLCHAIN_PATH' "$c")
        export LLVM_PATH=$(jq -r '.LLVM_PATH' "$c")
        export FLAGS=$(jq -r '.FLAGS' "$c")
        export OPT_FLAGS=$(jq -r '.OPT_FLAGS[]' "$c")
        export RESULTS_PATH=$(jq -r '.RESULTS_PATH' "$c")
        export NUM_CPU_CORES=$(jq -r '.NUM_CPU_CORES' "$c")
        # Backup the original number of CPU cores
        OLD_NUM_CPU_CORES=$NUM_CPU_CORES
        export PIN_CMD=$(jq -r '.PIN_CMD' "$c")

        # Verify the paths
        [ ! -d $PTS_BASE ] && echo "PTS not found!" && exit 1
        [ ! -d $TEST_PROFILES_PATH ] && echo "Test profiles not found!" && exit 1
        [ ! -d $TOOLCHAIN_PATH ] && echo "Toolchain not found!" && exit 1
        [ ! -d $LLVM_PATH ] && echo "LLVM not found!" && exit 1
        [ ! -d $RESULTS_PATH ] && mkdir $RESULTS_PATH

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

        # Phoronix test suite command
        export PTS="$PTS_BASE/phoronix-test-suite"

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

        # Export basename variable, used to measure compile time in toolchain/
        export basename=$(basename $p)

        # Point to the toolchain wrappers
        export CC=$TOOLCHAIN_PATH/clang
        export CXX=$TOOLCHAIN_PATH/clang++

        # Loop over opt flags
        for opt_flag in $OPT_FLAGS; do
            # Set compiler flags
            export CFLAGS=$FLAGS" "$opt_flag
            export CXXFLAGS=$FLAGS" "$opt_flag

            # Set original number of CPU cores
            export NUM_CPU_CORES=$OLD_NUM_CPU_CORES

            # Export current optimization flag
            export OPT_FLAG=$opt_flag

            # Install and measure compile time and memory usage
            $PTS batch-install $p

            # Measure object size
            SIZE_DIR=$RESULTS_PATH/object-size/$(echo $p | cut -d'/' -f2)/$CONFIG_NAME
            [ ! -d $SIZE_DIR ] && mkdir -p $SIZE_DIR
            du -ab $RESULTS_PATH/installed-tests/$p | while read size file; do
                echo -e "$size\t$file\t$(file -b "$file")"
            done > $SIZE_DIR/$(echo $opt_flag | tr -d '-')

            # Run tests with a single CPU core
            OLD_NUM_CPU_CORES=$NUM_CPU_CORES
            export NUM_CPU_CORES=1

            # Run the test
            result_name=`echo $p | cut -d'/' -f2`"_"
            echo -n $result_name | $PTS batch-run $p

            # Copy results
            pushd $RESULTS_PATH
            cp -r compile-time $RESULTS_REPO
            cp -r object-size $RESULTS_REPO
            cp -r memory-usage $RESULTS_REPO
            for dir in test-results/*; do
                mkdir -p $dir/$CONFIG_NAME/$(echo $opt_flag | tr -d '-')
                mv $dir/* $dir/$CONFIG_NAME/$(echo $opt_flag | tr -d -)
            done
            cp -r test-results $RESULTS_REPO

            rm -rf compile-time installed-tests object-size memory-usage test-results
            popd

            pushd $RESULTS_REPO
            git add .
            git commit --no-gpg-sign -m "$CONFIG_NAME($(echo $opt_flag | tr -d '-')): $p"
            git push -f
            popd
        done
    done

    pushd $RESULTS_REPO
    find . -name "s,^.*" | xargs rm -rf
    popd
    # TODO: HARDCODED -O2
    python3 results-to-csv.py $RESULTS_REPO $TEST_PROFILES_PATH "O2" -mp

    # Write README.md
    echo "# $FORMATTED_DATE @ $(hostname)" > $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## Compilation Time" >> $RESULTS_REPO/README.md
    echo "![Compilation Time](plots/compile-time.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## Memory Usage" >> $RESULTS_REPO/README.md
    echo "![Memory Usage](plots/memory-usage.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## Object Size" >> $RESULTS_REPO/README.md
    echo "![Object Size](plots/object-size.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## Runtime" >> $RESULTS_REPO/README.md
    echo "![Runtime](plots/runtime.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md

    pushd $RESULTS_REPO
    git add -A
    git commit --no-gpg-sign --amend --no-edit
    git push -f
    popd

done

rm -rf $RESULTS_PATH/installed-tests/*
rm -rf $RESULTS_PATH/test-results/*
rm -rf $RESULTS_PATH/object-size/*
rm -rf $RESULTS_PATH/compile-time/*
rm -rf $RESULTS_PATH/memory-usage/*
