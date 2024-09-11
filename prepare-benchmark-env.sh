#!/bin/bash -x

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
