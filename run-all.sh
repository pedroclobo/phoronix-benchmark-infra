#!/bin/bash

# Function to display usage
usage() {
    echo "Usage: $0 [options] <base_config> <other_config> <results_repo> <profiles_file> <pts_base> <test_profiles_path> <toolchain_path> <install_path>"
    echo ""
    echo "Arguments:"
    echo "  <base_config>                 JSON configuration"
    echo "  <other_config>                JSON configuration"
    echo "  <results_repo>                Repository to store results"
    echo "  <profiles_file>               File containing test profiles to run"
    echo "  <pts_base>                    Path to Phoronix Test Suite"
    echo "  <test_profiles_path>          Path to test profiles"
    echo "  <toolchain_path>              Path to toolchain directory"
    echo "  <install_path>                Path for installing tests"
    echo ""
    echo "Options:"
    echo "  -p, --prepare                 Tweak environment to decrease result variance (needs sudo)"
    echo "  -i, --install-only            Only install the tests"
    echo "  -r, --follow-inline-remarks   Follow baseline inline marks in prototype"
    echo "  -h, --help                    Display this message"
    exit 1
}

# Default behavior
run_prepare=0
install_only=0
follow_inline_remarks=0

# Parse command line arguments
TEMP=$(getopt -o phi --long prepare,help,install-only,follow-inline-remarks -n "$0" -- "$@")
if [ $? != 0 ] ; then echo "Termination..." >&2 ; exit 1 ; fi
eval set -- "$TEMP"

while true; do
    case "$1" in
        -p | --prepare)
            run_prepare=1
            shift
        ;;
        -i | --install-only)
            install_only=1
            shift
        ;;
        -r | --follow-inline-remarks)
            follow_inline_remarks=1
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

        # Refresh inline remarks
        INLINE_REMARKS_DIR=$RESULTS_REPO/inline-remarks/$(echo $p | cut -d'/' -f2)/${CONFIG_NAME}
        [ ! -d $INLINE_REMARKS_DIR ] && mkdir -p $INLINE_REMARKS_DIR
        INLINE_REMARKS_FILE=$INLINE_REMARKS_DIR/$(echo $OPT_FLAG | tr -d -).txt
        rm -f $INLINE_REMARKS_FILE

        # Follow inline remarks
        if [ "$CONFIG_NAME" = "byte" ] && [ $follow_inline_remarks -eq 1 ]; then
            INLINE_REMARKS_FILE=$RESULTS_REPO/inline-remarks/$(echo $p | cut -d'/' -f2)/base/$(echo $OPT_FLAG | tr -d '-').txt
            CFLAGS="$CFLAGS -mllvm -cgscc-inline-replay=$INLINE_REMARKS_FILE"
        fi

        # Set original number of CPU cores
        export NUM_CPU_CORES=$OLD_NUM_CPU_CORES

        # Install and measure compile time and memory usage
        [[ $install_only -eq 1 ]] && rounds=1 || rounds=3
        for ((i=1; i<=rounds; i++)); do
            echo "Installing $p ($i/$rounds)"
            rm -rf $INSTALL_DIR
            export INSTALL_ROUND=$i
            $PTS batch-install $p
        done

        # Exit early if install-only is set
        if [[ $install_only -eq 1 ]]; then
            echo "Install-only flag is set, skipping test execution and analysis for $p"
            continue
        fi

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

    # Exit early if install-only is set
    if [[ $install_only -eq 1 ]]; then
        echo "Install-only flag is set, skipping assembly difference for $p"
        continue
    fi

    # Compare assembly generated by both profiles
    test_name=$(echo $p | cut -d'/' -f2)
    echo "Comparing assembly for $test_name..."

    ASM_DIFF_DIR=$RESULTS_REPO/asm-diff/$test_name/$(echo $OPT_FLAG | tr -d '-')
    [ ! -d $ASM_DIFF_DIR ] && mkdir -p $ASM_DIFF_DIR

    # Create two files for this test
    diff_func_file="$ASM_DIFF_DIR/diff.txt"
    all_func_file="$ASM_DIFF_DIR/all.txt"
    # Add new file for less strict comparison
    diff_loose_file="$ASM_DIFF_DIR/diff_loose.txt"

    # Define paths to installed binaries for both configurations
    BASE_DIR=$INSTALL_PATH/installed-tests/$(basename $BASE_CONFIG .json)/$p
    OTHER_DIR=$INSTALL_PATH/installed-tests/$(basename $OTHER_CONFIG .json)/$p

    # Find all ELF files in base dir
    elf_files=$(find $BASE_DIR -type f -exec file {} \; | grep -E "ELF" | cut -d':' -f1)

    # Define timeout status file path in asm-diff directory
    TIMEOUT_FILE=$RESULTS_REPO/asm-diff/$test_name/$(echo $OPT_FLAG | tr -d '-')/timeout.txt
    touch $TIMEOUT_FILE

    # Run assembly comparison with timeout
    timeout 10m bash -c "
        find $BASE_DIR -type f -exec file {} \; | grep -E 'ELF' | cut -d':' -f1 | while read -r base_file; do
            rel_path=\${base_file#$BASE_DIR/}
            other_file=$OTHER_DIR/\$rel_path
            [ ! -f \"\$other_file\" ] && continue

            # Create temporary files for objdump output
            base_dump=\$(mktemp)
            other_dump=\$(mktemp)

            # Generate assembly dumps with Intel syntax and no addresses
            objdump -d -Mintel --no-addresses --no-show-raw-insn \"\$base_file\" > \"\$base_dump\" 2>/dev/null
            objdump -d -Mintel --no-addresses --no-show-raw-insn \"\$other_file\" > \"\$other_dump\" 2>/dev/null

            # Create binary-specific output files
            binary_diff_file=\"${diff_func_file}.\$(basename \"\$base_file\")\"
            binary_all_file=\"${all_func_file}.\$(basename \"\$base_file\")\"
            binary_loose_file=\"${diff_loose_file}.\$(basename \"\$base_file\")\"

            # Create empty files
            rm -f \"\$binary_diff_file\" \"\$binary_all_file\" \"\$binary_loose_file\"
            touch \"\$binary_diff_file\" \"\$binary_all_file\" \"\$binary_loose_file\"

            # Get all functions from both binaries
            functions=\$(grep -E '^<.*>:' \"\$base_dump\" | sed -E 's/^<(.*)>:/\\1/g' | sort -u)

            while read -r func; do
                # Skip empty lines and special characters
                [ -z \"\$func\" ] || echo \"\$func\" | grep -q '[<>]' && continue

                # Extract function contents
                base_func=\$(sed -n \"/^<\$func>:/,/^<.*>:/p\" \"\$base_dump\" | sed '\$d')
                other_func=\$(sed -n \"/^<\$func>:/,/^<.*>:/p\" \"\$other_dump\" | sed '\$d')

                # Add to all functions list
                echo \"\$func\" >> \"\$binary_all_file\"

                # Skip if function doesn't exist in both binaries
                [ -z \"\$base_func\" ] || [ -z \"\$other_func\" ] && continue

                # === STRICT COMPARISON ===
                # Compare raw function contents (exact match check)
                if [ \"\$base_func\" != \"\$other_func\" ]; then
                    echo \"\$func\" >> \"\$binary_diff_file\"

                    # === SIMPLIFIED LOOSE COMPARISON ===
                    # Get just the instruction content without function headers
                    base_content=\$(echo \"\$base_func\" | grep -v '^<.*>:')
                    other_content=\$(echo \"\$other_func\" | grep -v '^<.*>:')

                    # Clean the content for better comparison (simpler now without addresses)
                    base_clean=\$(echo \"\$base_content\" | sed 's/^[[:space:]]*//' | grep -v '^$')
                    other_clean=\$(echo \"\$other_content\" | sed 's/^[[:space:]]*//' | grep -v '^$')

                    # Create temporary files for the cleaned content
                    base_temp=\$(mktemp)
                    other_temp=\$(mktemp)
                    echo \"\$base_clean\" > \"\$base_temp\"
                    echo \"\$other_clean\" > \"\$other_temp\"

                    # Simple check: if line counts differ, there must be added/removed lines
                    if [ \"\$(wc -l < \"\$base_temp\")\" -ne \"\$(wc -l < \"\$other_temp\")\" ]; then
                        echo \"\$func\" >> \"\$binary_loose_file\"
                    else
                        # Use a simplified approach to check for added/removed lines
                        # Create a line-by-line diff
                        diff_result=\$(diff \"\$base_temp\" \"\$other_temp\" || true)

                        # Check for isolated additions or removals
                        if echo \"\$diff_result\" | grep -q -E '^(<|>)'; then
                            # Count < and > lines
                            removed=\$(echo \"\$diff_result\" | grep -c '^<')
                            added=\$(echo \"\$diff_result\" | grep -c '^>')

                            # If the counts are different, there are true additions or removals
                            if [ \"\$removed\" -ne \"\$added\" ]; then
                                echo \"\$func\" >> \"\$binary_loose_file\"
                            fi
                        fi
                    fi

                    # Clean up temporary files
                    rm -f \"\$base_temp\" \"\$other_temp\"
                fi
            done <<< \"\$functions\"

            # Append binary-specific results to main files
            cat \"\$binary_diff_file\" >> \"$diff_func_file\" 2>/dev/null || true
            cat \"\$binary_all_file\" >> \"$all_func_file\" 2>/dev/null || true
            cat \"\$binary_loose_file\" >> \"$diff_loose_file\" 2>/dev/null || true

            # Clean up temporary files
            rm -f \"\$base_dump\" \"\$other_dump\" \"\$binary_diff_file\" \"\$binary_all_file\" \"\$binary_loose_file\"
        done

        # Sort and deduplicate results
        sort -u \"$diff_func_file\" -o \"$diff_func_file\"
        sort -u \"$all_func_file\" -o \"$all_func_file\"
        sort -u \"$diff_loose_file\" -o \"$diff_loose_file\"
    " >/dev/null 2>&1

    # Check if timeout occurred (exit code 124)
    [ $? -eq 124 ] && echo "y" > $TIMEOUT_FILE || echo "n" > $TIMEOUT_FILE

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
    [ $follow_inline_remarks -eq 1 ] && checkbox="[x]" || checkbox="[ ]"
    echo "Follow inline remarks: $checkbox" >> "$RESULTS_REPO/README.md"
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
    echo "## ASM Size" >> $RESULTS_REPO/README.md
    echo "![ASM Size](plots/asm-size.svg)" >> $RESULTS_REPO/README.md
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
