#!/usr/bin/env bash
# GPS Stamp Date Changer Pro - Linux & macOS Launcher

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "      GPS STAMP DATE CHANGER PRO - CROSS-PLATFORM         "
echo "=========================================================="

# Check for Python 3
if command -v python3 &>/dev/null; then
    PYTHON_CMD=python3
elif command -v python &>/dev/null; then
    PYTHON_CMD=python
else
    echo "[ERROR] Python 3 was not found. Please install Python 3.10+."
    exit 1
fi

echo "[1/3] Verifying Python environment..."
$PYTHON_CMD -m pip install -r requirements.txt --quiet

if [ ! -f "samples/IMG001.jpg" ]; then
    echo "[2/3] Generating test sample data..."
    $PYTHON_CMD generate_samples.py
fi

echo "[3/3] Starting GPS Stamp Date Changer Pro on http://127.0.0.1:8000 ..."
if command -v xdg-open &>/dev/null; then
    xdg-open "http://127.0.0.1:8000" &
elif command -v open &>/dev/null; then
    open "http://127.0.0.1:8000" &
fi

$PYTHON_CMD desktop_app.py
