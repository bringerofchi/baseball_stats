#!/bin/bash
# Double-click this file to start the MLB Edge Lab dashboard.
# (First time only: you may need to right-click -> Open, since it's not
# from the App Store — macOS blocks unsigned scripts by default on a
# plain double-click.)

cd "$(dirname "$0")"
echo "Setting up (first run installs a few packages, this may take a minute)..."
python3 -m pip install -r requirements.txt --break-system-packages --quiet 2>/dev/null || python3 -m pip install -r requirements.txt --quiet
echo "Starting dashboard..."
python3 webapp/app.py
