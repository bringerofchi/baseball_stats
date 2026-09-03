@echo off
REM Run from the project root (same folder as run_server.bat), e.g.:
REM   cd "C:\Users\justi\OneDrive\Desktop\baseball stats\mlb_edge_lab"
REM   orchestrator\run_orchestrator.bat
cd /d "%~dp0.."
python orchestrator\runner.py
pause
