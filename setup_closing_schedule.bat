@echo off
REM One-time setup: registers a Windows Task Scheduler job that automatically
REM fetches closing odds throughout the day, so you don't have to click the
REM dashboard button multiple times to catch each game's closing line before
REM it starts.
REM
REM Double-click this file ONCE. After that it runs in the background
REM automatically, every day, even if the dashboard/browser isn't open.
REM Re-run this file if you ever move the project to a different folder.
REM
REM INTERVAL: defaults to every 60 minutes, from 11:00 AM to 11:00 PM.
REM Why hourly, not more often: The Odds API's free tier is 500 CREDITS
REM per month, and each call to fetch odds costs 1 credit (after the
REM moneyline-only fix in clients/odds_api.py). Running every 30 minutes
REM instead of 60 would roughly double monthly usage and risk running out
REM before the month ends. Hourly (~13 calls/day across a 12-hour window)
REM plus one daily morning call stays comfortably under budget with room
REM to spare. Change INTERVAL_MINUTES below if you're on a paid Odds API
REM plan with a higher quota and want tighter coverage.

setlocal
set INTERVAL_MINUTES=60
set START_TIME=11:00
set DURATION=12:00

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

echo Registering scheduled task "MLB Edge Lab - Closing Odds"...
echo   Project folder: %PROJECT_DIR%
echo   Python: %PYTHON_PATH%
echo   Runs every %INTERVAL_MINUTES% minutes, %START_TIME% to close of window (%DURATION% duration), daily.
echo.

schtasks /create /tn "MLB Edge Lab - Closing Odds" ^
    /tr "\"%PYTHON_PATH%\" \"%PROJECT_DIR%\main.py\" closing --date today" ^
    /sc daily /st %START_TIME% /ri %INTERVAL_MINUTES% /du %DURATION% /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Success. Closing odds will now fetch automatically in the background
    echo every day - no need to keep any window open, no need to click anything.
    echo.
    echo To check on it: open Task Scheduler (search "Task Scheduler" in Start),
    echo look for "MLB Edge Lab - Closing Odds" in the task list.
    echo.
    echo To remove it later: run uninstall_closing_schedule.bat, or delete it
    echo from Task Scheduler directly.
) else (
    echo.
    echo Something went wrong. Try right-clicking this file and choosing
    echo "Run as administrator", then try again.
)
pause
