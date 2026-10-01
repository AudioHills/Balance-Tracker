@echo off
REM Builds dist\BalanceTracker.exe on Windows.
REM Requires Python 3.10+ from python.org (tick "Add python.exe to PATH" during install).
setlocal
cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

echo Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements-dev.txt || goto :error

echo Running tests...
python -m pytest -q || goto :error

echo Building BalanceTracker.exe...
pyinstaller --noconfirm --clean --onefile --windowed ^
    --name BalanceTracker ^
    --icon assets\icon.ico ^
    main.py || goto :error

echo.
echo Done! Your program is at: %cd%\dist\BalanceTracker.exe
pause
exit /b 0

:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1
