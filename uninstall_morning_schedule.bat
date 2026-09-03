@echo off
REM Removes the "MLB Edge Lab - Morning Ingest" scheduled task created by
REM setup_morning_schedule.bat. Double-click to run.

echo Removing scheduled task "MLB Edge Lab - Morning Ingest"...
schtasks /delete /tn "MLB Edge Lab - Morning Ingest" /f

if %ERRORLEVEL% EQU 0 (
    echo Done. Automatic morning ingest is now off.
) else (
    echo Nothing to remove, or something went wrong - check Task Scheduler
    echo directly if you're unsure.
)
pause
