#!/bin/bash -x

# Validate arguments
if [ $# -ne 1 ]; then
	echo "Usage: $0 <0|1>"
	exit 1
fi

if [ $1 -ne 0 ] && [ $1 -ne 1 ]; then
	echo "Usage: $0 <0|1>"
	exit 1
fi

if [ $1 -eq 0 ]; then
	# Revert turbo boost
	echo "0" | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo

	# Revert hyperthreading
	echo on | sudo tee /sys/devices/system/cpu/smt/control

	# Revert CPU frequency governor
	sudo cpupower frequency-set -g performance

	# Revert ASLR
	echo 2 | sudo tee /proc/sys/kernel/randomize_va_space
fi

if [ $1 -eq 1 ]; then
	# Disable turbo boost
	echo "1" | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo

	# Disable hyperthreading
	echo off | sudo tee /sys/devices/system/cpu/smt/control

	# Put CPUs in max frequency with performance governor
	sudo cpupower frequency-set -g performance \
		--min `cpupower frequency-info | grep "hardware limits" | awk '{print $6,$7}' | tr -d ' '` \
		--max `cpupower frequency-info | grep "hardware limits" | awk '{print $6,$7}' | tr -d ' '`

	# Disable ASLR
	echo 0 | sudo tee /proc/sys/kernel/randomize_va_space
fi
