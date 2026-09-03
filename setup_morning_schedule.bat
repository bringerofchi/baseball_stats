@echo off
REM One-time setup: registers a Windows Task Scheduler job that automatically
REM runs the morning/opening ingest every day BEFORE the earliest MLB game
REM starts, so day games never get missed just because the dashboard wasn't
REM opened yet. This closes a real gap: live-odds endpoints (The Odds API,
REM ParlayAPI, SharpAPI) only serve upcoming/live games — once a game
REM starts (let alone finishes), there is no way to retroactively fetch its
REM pregame line from any of them. A day game that's already over by the
REM time you first click "Run Morning" that day permanently has no market
REM data for the SP-mismatch signal, for that game, for that day.
REM
REM Double-click this file ONCE. After that it runs in the background
REM automatically, every day, even if the dashboard/browser isn't open.
REM Re-run this file if you ever move the project to a different folder.
REM
REM DEFAULT TIME: 7:00 AM local time. The earliest MLB day games are
REM usually not before ~11:00 AM local (day-after-getaway-day businessman's
REM specials), so 7:00 AM gives a comfortable margin. Change START_TIME
REM below if you want it earlier/later.

setlocal
set START_TIME=07:00

set PROJECT_DIR=%~dp0
set PROJECT_DIR=%PROJECT_DIR:~0,-1%

for /f "delims=" %%P in ('where python') do (
    set PYTHON_PATH=%%P
    goto :found
)
:found

if "%PYTHON_PATH%"=="" (
    echo Could not find python.exe on your PATH. Make sure Python is installed
    echo and re-run this file.
    pause
    exit /b 1
)

echo Registering scheduled task "MLB Edge Lab - Morning Ingest"...
echo   Project folder: %PROJECT_DIR%
echo   Python: %PYTHON_PATH%
echo   Runs once daily at %START_TIME%.
echo.

schtasks /create /tn "MLB Edge Lab - Morning Ingest" ^
    /tr "\"%PYTHON_PATH%\" \"%PROJECT_DIR%\main.py\" morning --date today" ^
    /sc daily /st %START_TIME% /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Success. The morning/opening ingest will now run automatically every
    echo day at %START_TIME% - no need to remember to click it before the
    echo first game of the day starts.
    echo.
    echo To check on it: open Task Scheduler (search "Task Scheduler" in Start),
    echo look for "MLB Edge Lab - Morning Ingest" in the task list.
    echo.
    echo To see what it did: check the Logs tab in the dashboard, or
    echo logs\mlb_edge_lab.log directly.
    echo.
    echo To remove it later: run uninstall_morning_schedule.bat, or delete it
    echo from Task Scheduler directly.
) else (
    echo.
    echo Something went wrong. Try right-clicking this file and choosing
    echo "Run as administrator", then try again.
)
pause
