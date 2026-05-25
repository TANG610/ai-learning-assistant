@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   AI Learning Assistant v2.0
echo ==========================================

set PYTHON_EXE=python
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set PYTHON_EXE=%CONDA_PREFIX%\python.exe
if exist "D:\Software\anaconda3\envs\aipm\python.exe" set PYTHON_EXE=D:\Software\anaconda3\envs\aipm\python.exe

"%PYTHON_EXE%" --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found. Activate the aipm environment first.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import chromadb" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing Python dependencies...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
)

if not exist ".env" (
    echo [WARN] .env was not found.
    if exist ".env.example" copy ".env.example" ".env" >nul
    echo [WARN] Please edit .env and set your LLM API key.
    notepad ".env"
)

set HF_HUB_OFFLINE=0
set TRANSFORMERS_OFFLINE=0
set WHISPER_MODEL_PATH=%CD%\models\faster-whisper-small
set CHROMA_HOST=127.0.0.1
set CHROMA_PORT=8000

for %%i in ("%PYTHON_EXE%") do set PYTHON_DIR=%%~dpi
set CHROMA_EXE=
if exist "%PYTHON_DIR%Scripts\chroma.exe" set CHROMA_EXE=%PYTHON_DIR%Scripts\chroma.exe
if exist "%PYTHON_DIR%chroma.exe" set CHROMA_EXE=%PYTHON_DIR%chroma.exe
if not defined CHROMA_EXE set CHROMA_EXE=chroma

netstat -ano | findstr /R /C:"127.0.0.1:%CHROMA_PORT% .*LISTENING" >nul
if errorlevel 1 (
    echo.
    echo [INFO] Starting Chroma vector database...
    start "Chroma Vector DB" cmd /k call "%CHROMA_EXE%" run --path "%CD%\data\vector_db" --host %CHROMA_HOST% --port %CHROMA_PORT%
    ping 127.0.0.1 -n 9 >nul
) else (
    echo [INFO] Chroma is already running on %CHROMA_HOST%:%CHROMA_PORT%.
)

netstat -ano | findstr /R /C:"127.0.0.1:5000 .*LISTENING" >nul
if errorlevel 1 (
    echo.
    echo [INFO] Starting Flask backend and frontend...
    start "AI Learning Assistant" cmd /k call "%PYTHON_EXE%" backend\app.py
    ping 127.0.0.1 -n 4 >nul
) else (
    echo [INFO] Flask is already running on 127.0.0.1:5000.
)

start http://127.0.0.1:5000

echo ==========================================
echo   Startup complete.
echo   Open: http://127.0.0.1:5000
echo ==========================================
pause
