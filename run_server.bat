@echo off
REM Double-click this file to start the MLB Edge Lab dashboard.
cd /d %~dp0
echo Setting up (first run installs a few packages, this may take a minute)...
python -m pip install -r requirements.txt --quiet
echo Starting dashboard...
python webapp\app.py
pause
