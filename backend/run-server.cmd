@echo off
setlocal EnableExtensions
title LogicLens API - http://localhost:8000
rem ===========================================================================
rem  Runs the LogicLens API on http://localhost:8000 (started by Start-LogicLens.cmd).
rem  First start: creates .venv here and installs requirements.txt.
rem  Image recognition: YOLO model in ..\ml\models + Tesseract OCR if installed.
rem  AI explain/chat/vision: set ANTHROPIC_API_KEY in your Windows environment.
rem ===========================================================================
cd /d "%~dp0"

if not defined PY call :find_python
if not defined PY goto no_python

if exist ".venv\Scripts\python.exe" goto venv_ok
echo Creating the Python environment - first start only...
%PY% -m venv .venv
if errorlevel 1 goto venv_failed

:venv_ok
if exist ".venv\installed-v2.txt" goto deps_ok
echo.
echo Installing the API's Python packages - first start only.
echo This downloads about 45 MB and takes 2 to 5 minutes. Please leave this window open.
echo.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto pip_failed
echo installed> ".venv\installed-v2.txt"
echo.
echo Packages installed.

:deps_ok
set "LOGICLENS_YOLO_ONNX=%~dp0..\ml\models\logiclens-yolov8n.onnx"
set "LOGICLENS_ENGINE=auto"
set "TESS="
where tesseract >nul 2>nul
if not errorlevel 1 set "TESS=tesseract"
if not defined TESS if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "TESS=%ProgramFiles%\Tesseract-OCR\tesseract.exe"
if not defined TESS if exist "%LocalAppData%\Programs\Tesseract-OCR\tesseract.exe" set "TESS=%LocalAppData%\Programs\Tesseract-OCR\tesseract.exe"
if defined TESS goto tess_ok
set "LOGICLENS_OCR=false"
echo.
echo NOTE: Tesseract OCR is not installed, so tag names in recognised rungs show as "?".
echo       Install it from https://github.com/UB-Mannheim/tesseract/wiki and restart.
echo.
goto run

:tess_ok
set "LOGICLENS_TESSERACT_CMD=%TESS%"

:run
echo Starting the LogicLens API on http://localhost:8000 - keep this window open.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto end

:no_python
echo Python 3.11 to 3.13 was not found.
echo Install Python 3.12 from https://www.python.org - tick "Add python.exe to PATH" -
echo then run Start-LogicLens.cmd again.
goto end

:venv_failed
echo Could not create the Python environment - see the message above.
goto end

:pip_failed
echo Installing the Python packages failed - see the messages above
echo (most often: no internet connection, or a Python version without ready-made packages).
goto end

:find_python
set "PY="
for %%V in (3.13 3.12 3.11) do call :try_py %%V
if defined PY goto :eof
python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
goto :eof

:try_py
if defined PY goto :eof
py -%1 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -%1"
goto :eof

:end
endlocal
