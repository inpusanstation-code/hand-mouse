@echo off
setlocal
chcp 65001 > nul

rem MANUX Preview Launcher
echo ========================================================
echo   Starting MANUX Preview (Pose Studio + Spatial MLP)
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/2] Checking dependencies...
call uv sync --extra vision --extra ui --extra ml
if errorlevel 1 (
    echo [ERROR] Failed to sync packages with uv.
    pause
    exit /b %errorlevel%
)

echo.
echo [2/2] Launching MANUX Desktop Application...
echo.
echo * Hotkeys in App:
echo   - Click [Pose Studio (MLP)] on top/sidebar
echo   - Keys 1 to 8: Select gesture class
echo   - Space: Start/Stop continuous recording
echo   - Train button: Instant 4s Spatial MLP training
echo.

call uv run python -m manux
set "APP_EXIT=%errorlevel%"

rem Closing the app closes this window too. Only on an error the window stays so the message can be read.
if not "%APP_EXIT%"=="0" (
    echo.
    echo [Notice] App exited with error code %APP_EXIT%.
    echo          Error log: %APPDATA%\MANUX-dev\v04\logs\errors.log
    echo          Press any key to close.
    pause > nul
)
endlocal & exit %APP_EXIT%
