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
rem train + hub: the Learning Center's worker (TCN training needs torch/onnx, its self-check also loads huggingface_hub).
rem With an NVIDIA GPU the CUDA build of torch is kept, as virtual-hand-20261110\setup-tcn.cmd did: uv sync leaves torch
rem alone (--no-install-package torch --inexact; a plain sync would put the CPU build from uv.lock back on every
rem launch) and the CUDA build (cu132, docs\hardware-acceleration.md) is installed only when it is missing.
set "SYNC=uv sync --extra vision --extra ui --extra ml --extra train --extra hub"
where nvidia-smi >nul 2>nul
if errorlevel 1 goto cpu_sync

call %SYNC% --no-install-package torch --inexact
if errorlevel 1 goto sync_failed
".venv\Scripts\python.exe" -c "import sys, torch; sys.exit(0 if torch.version.cuda else 1)" >nul 2>nul
if not errorlevel 1 goto synced
echo NVIDIA GPU detected: installing the CUDA build of PyTorch (first time only, large download)...
call uv pip install --python ".venv\Scripts\python.exe" --reinstall-package torch torch==2.15.0 --index-url https://download.pytorch.org/whl/cu132
if not errorlevel 1 goto synced
echo [WARN] Could not install CUDA PyTorch. Using the CPU build for now; training will run on the CPU.

:cpu_sync
call %SYNC%
if errorlevel 1 goto sync_failed

:synced
echo.
echo [2/2] Launching MANUX Desktop Application...
echo.
echo * Hotkeys in App:
echo   - Click [Pose Studio (MLP)] on top/sidebar
echo   - Keys 1 to 8: Select gesture class
echo   - Space: Start/Stop continuous recording
echo   - Train button: Instant 4s Spatial MLP training
echo.

rem --no-sync: the packages were prepared above (uv run would otherwise swap the CUDA torch for the locked CPU one).
call uv run --no-sync python -m manux
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

:sync_failed
echo [ERROR] Failed to sync packages with uv.
pause
endlocal & exit /b 1
