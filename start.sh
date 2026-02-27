#!/bin/bash
# Rium GM Dosimeter Launcher for Linux/macOS
# ASNR (formerly IRSN) Project

echo ""
echo "============================================================"
echo "  RIUM GM DOSIMETER READER - Launcher"
echo "  ASNR (formerly IRSN) Project"
echo "============================================================"
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo ""
    echo "Please install Python 3.7 or higher:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "  macOS: brew install python3"
    echo ""
    exit 1
fi

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Run the launcher
python3 launcher.py
