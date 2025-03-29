#!/bin/bash

# Function to display usage
usage() {
    echo "Usage: $0 [options] <base_config> <other_config> <results_repo> <profiles_file> <pts_base> <test_profiles_path> <toolchain_path> <install_path>"
    echo ""
    echo "Arguments:"
    echo "  <base_config>         JSON configuration"
    echo "  <other_config>        JSON configuration"
    echo "  <results_repo>        Repository to store results"
    echo "  <profiles_file>       File containing test profiles to run"
    echo "  <pts_base>            Path to Phoronix Test Suite"
    echo "  <test_profiles_path>  Path to test profiles"
    echo "  <toolchain_path>      Path to toolchain directory"
    echo "  <install_path>        Path for installing tests"
    echo ""
    echo "Options:"
    echo "  -p, --prepare         Tweak environment to decrease result variance (needs sudo)"
    echo "  -h, --help            Display this message"
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
[ $# -ne 8 ] && usage
BASE_CONFIG="$1"
OTHER_CONFIG="$2"
export RESULTS_REPO="$3"
PROFILES_FILE="$4"
export PTS_BASE="$5"
export TEST_PROFILES_PATH="$6"
export TOOLCHAIN_PATH="$7"
export INSTALL_PATH="$8"
export PTS="$PTS_BASE/phoronix-test-suite"

[ ! -f "$BASE_CONFIG" ] && echo "Base config file does not exist: $BASE_CONFIG" && exit 1
[ ! -f "$OTHER_CONFIG" ] && echo "Other config file does not exist: $OTHER_CONFIG" && exit 1
[ ! -d "$RESULTS_REPO" ] && echo "Results repository does not exist: $RESULTS_REPO" && exit 1
[ ! -d "$RESULTS_REPO/.git" ] && echo "Results repository is not a git repository!" && exit 1
[ ! -f "$PROFILES_FILE" ] && echo "Profiles file does not exist: $PROFILES_FILE" && exit 1
[ ! -d "$PTS_BASE" ] && echo "PTS not found: $PTS_BASE" && exit 1
[ ! -d "$TEST_PROFILES_PATH" ] && echo "Test profiles not found: $TEST_PROFILES_PATH" && exit 1
[ ! -d "$TOOLCHAIN_PATH" ] && echo "Toolchain not found: $TOOLCHAIN_PATH" && exit 1

# Prepare environement to decrease result variance (needs sudo)
[[ $run_prepare -eq 1 ]] && ./prepare-benchmark-env.sh 1

# Create new branch in results repo
pushd $RESULTS_REPO
DATE=$(date +%Y-%m-%d-%H-%M-%S)
FORMATTED_DATE=$(date +"%d %B %Y - %H:%M")
git checkout --orphan $DATE-$(hostname | cut -d'.' -f1)
git rm -rf .
git clean -df
popd

export PTS_SILENT_MODE=TRUE
export TEST_RESULTS_NAME=$(hostname | cut -d'.' -f1)

# Generate phoronix user configuration
batch_setup=$(
    # Save test results when in batch mode
    echo y && \
    # Open the web browser automatically when in batch mode
    echo n && \
    # Auto upload the results to OpenBenchmarking.org
    echo n && \
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

# Delete previously installed tests
[ ! -d $INSTALL_PATH ] && mkdir $INSTALL_PATH
rm -rf $INSTALL_PATH/installed-tests/*

# Delete previous test results
rm -rf ~/.phoronix-test-suite/test-results/$(hostname | cut -d'.' -f1)

for p in $(grep -v '#' $PROFILES_FILE); do
    for c in $BASE_CONFIG $OTHER_CONFIG; do
        # Parse the config file
        export CONFIG_NAME=$(basename "$c" .json)
        export LLVM_PATH=$(jq -r '.LLVM_PATH' "$c")
        export FLAGS=$(jq -r '.FLAGS' "$c")
        export OPT_FLAG=$(jq -r '.OPT_FLAG' "$c")
        export NUM_CPU_CORES=$(jq -r '.NUM_CPU_CORES' "$c")
        export PIN_CMD=$(jq -r '.PIN_CMD' "$c")

        # Backup original number of CPU cores
        OLD_NUM_CPU_CORES=$NUM_CPU_CORES

        [ ! -d $LLVM_PATH ] && echo "LLVM not found!" && exit 1

        # Export profile name to be used as a identifier in phoronix
        export TEST_RESULTS_IDENTIFIER=$CONFIG_NAME

        # Override PTS install directory
        export PTS_TEST_INSTALL_ROOT_PATH=$INSTALL_PATH/installed-tests/$CONFIG_NAME/
        [ ! -d $PTS_TEST_INSTALL_ROOT_PATH ] && mkdir -p $PTS_TEST_INSTALL_ROOT_PATH
        INSTALL_DIR=$PTS_TEST_INSTALL_ROOT_PATH"$p"

        # Export basename variable, used to measure compile time in toolchain/
        export basename=$(basename $p)

        # Point to the toolchain wrappers
        export CC=$TOOLCHAIN_PATH/clang
        export CXX=$TOOLCHAIN_PATH/clang++

        # Set compiler flags
        export CFLAGS=$FLAGS" "$OPT_FLAG
        export CXXFLAGS=$FLAGS" "$OPT_FLAG

        # Set original number of CPU cores
        export NUM_CPU_CORES=$OLD_NUM_CPU_CORES

        # Install and measure compile time and memory usage
        for i in {1..3}; do
            echo "Installing $p ($i/3)"
            rm -rf $INSTALL_DIR
            export INSTALL_ROUND=$i
            $PTS batch-install $p
        done

        # Measure object size
        SIZE_DIR=$RESULTS_REPO/object-size/$(echo $p | cut -d'/' -f2)/$CONFIG_NAME
        [ ! -d $SIZE_DIR ] && mkdir -p $SIZE_DIR
        SIZE_FILE=$SIZE_DIR/$(echo $OPT_FLAG | tr -d '-').txt
        find $INSTALL_DIR -type f -exec file {} \; |
          grep -Ei "ELF" | cut -d':' -f1 | while read -r file; do
            size=$(du -b "$file" | cut -f1)
            echo -e "$size\t$file"
        done > $SIZE_FILE

        # Measure asm function sizes
        ASM_DIR=$RESULTS_REPO/asm-diff/$(echo $p | cut -d'/' -f2)/$CONFIG_NAME/$(echo $OPT_FLAG | tr -d '-')
        [ ! -d $ASM_DIR ] && mkdir -p $ASM_DIR
        ASM_FILE=$ASM_DIR/sizes.txt
        find $INSTALL_DIR -type f -exec file {} \; \
        | grep -Ei "ELF" | cut -d':' -f1 | while read -r binary_file; do
            nm --size-sort -t d "$binary_file" |
            grep -E ' T | t ' | awk '{print $1, $3}' >> $ASM_FILE
        done
        sort -u -o $ASM_FILE $ASM_FILE

        # Run tests with a single CPU core
        OLD_NUM_CPU_CORES=$NUM_CPU_CORES
        export NUM_CPU_CORES=1

        # Run the test
        result_name=`echo $p | cut -d'/' -f2`"_"
        echo -n $result_name | $PTS batch-run $p
    done

    # Compare assembly generated by both profiles
    test_name=$(echo $p | cut -d'/' -f2)
    echo "Comparing assembly for $test_name..."

    ASM_DIFF_DIR=$RESULTS_REPO/asm-diff/$test_name/$(echo $OPT_FLAG | tr -d '-')
    [ ! -d $ASM_DIFF_DIR ] && mkdir -p $ASM_DIFF_DIR

    # Create two files for this test
    diff_func_file="$ASM_DIFF_DIR/diff.txt"
    all_func_file="$ASM_DIFF_DIR/all.txt"

    # Define paths to installed binaries for both configurations
    BASE_DIR=$INSTALL_PATH/installed-tests/$(basename $BASE_CONFIG .json)/$p
    OTHER_DIR=$INSTALL_PATH/installed-tests/$(basename $OTHER_CONFIG .json)/$p

    # Find all ELF files in base dir
    elf_files=$(find $BASE_DIR -type f -exec file {} \; | grep -E "ELF" | cut -d':' -f1)

    # These tests take too long to compare asm, skip them
    blacklist=("openssl")
    if [[ ! " ${blacklist[@]} " =~ " $test_name " ]]; then
        echo "$elf_files" | while read -r base_file; do
            rel_path=${base_file#$BASE_DIR/}
            other_file=$OTHER_DIR/$rel_path

            binary_name=$(basename "$base_file")
            base_dump=$(mktemp)
            other_dump=$(mktemp)

            # Dump disassembly
            objdump -d "$base_file" > "$base_dump" 2>/dev/null
            objdump -d "$other_file" > "$other_dump" 2>/dev/null

            # Extract function names only once
            functions=$(grep -E "^[0-9a-f]+ <.*>:" "$base_dump" | sed -E 's/^[0-9a-f]+ <(.*)>:/\1/g' | sort)

            while read -r func; do
                # Extract this function's assembly from both dumps
                base_func=$(sed -n "/^[0-9a-f]\+ <$func>:/,/^[0-9a-f]\+ <.*>:/p" "$base_dump" | sed '$d')
                other_func=$(sed -n "/^[0-9a-f]\+ <$func>:/,/^[0-9a-f]\+ <.*>:/p" "$other_dump" | sed '$d')

                [ "$base_func" != "$other_func" ] && echo "$func" >> "$diff_func_file"
                echo "$func" >> "$all_func_file"
            done <<< "$functions"

            # Clean up temp files
            rm -f "$base_dump" "$other_dump"
        done

        # Remove duplicates
        sort -u $diff_func_file -o $diff_func_file
        sort -u $all_func_file -o $all_func_file
    fi

    # Copy results
    pushd ~/.phoronix-test-suite
    xml_file="test-results/$(hostname | cut -d'.' -f1)/composite.xml"
    target_dir="$RESULTS_REPO/$(dirname $xml_file)/$(echo $OPT_FLAG | tr -d '-')"
    [ ! -d $target_dir ] && mkdir -p $target_dir
    cp $xml_file "$target_dir/"
    popd

    # TODO: HARDCODED -O2
    python3 results-to-csv.py $RESULTS_REPO $TEST_PROFILES_PATH "O3" -mp

    # Write README.md
    echo "# $FORMATTED_DATE @ $(hostname)" > $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## Compilation Time" >> $RESULTS_REPO/README.md
    echo "![Compilation Time](plots/compile-time.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## Runtime" >> $RESULTS_REPO/README.md
    echo "![Runtime](plots/runtime.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## Memory Usage" >> $RESULTS_REPO/README.md
    echo "![Memory Usage](plots/memory-usage.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## Object Size" >> $RESULTS_REPO/README.md
    echo "![Object Size](plots/object-size.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md
    echo "## ASM Diff" >> $RESULTS_REPO/README.md
    echo "![ASM Diff](plots/asm-diff.svg)" >> $RESULTS_REPO/README.md
    echo "" >> $RESULTS_REPO/README.md

    pushd $RESULTS_REPO
    find . -name "s,^.*" | xargs rm -rf
    git add .
    git commit --no-gpg-sign -m "$CONFIG_NAME($(echo $OPT_FLAG | tr -d '-')): $p"
    git push -f
    popd

done
