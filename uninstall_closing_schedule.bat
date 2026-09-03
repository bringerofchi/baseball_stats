@echo off
REM Removes the "MLB Edge Lab - Closing Odds" scheduled task created by
REM setup_closing_schedule.bat. Double-click to run.

echo Removing scheduled task "MLB Edge Lab - Closing Odds"...
schtasks /delete /tn "MLB Edge Lab - Closing Odds" /f

if %ERRORLEVEL% EQU 0 (
    echo Done. Automatic closing-odds fetching is now off.
) else (
    echo Nothing to remove, or something went wrong - check Task Scheduler
    echo directly if you're unsure.
)
pause
