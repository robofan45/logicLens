@echo off
setlocal EnableExtensions
rem ===========================================================================
rem  LogicLens v2 - double-click to start.
rem    Web app (needs Node.js 20 or newer)      -> opens http://localhost:5173
rem    API     (optional: Python 3.11 to 3.13)  -> screenshots and AI, port 8000
rem  No Node.js? Open LogicLens.html in this folder instead (text analysis).
rem  Every path below is quoted: this folder may contain "&" in its name.
rem  Safe to double-click again: a running copy is reused, not started twice.
rem ===========================================================================
set "ROOT=%~dp0"
set "PROBE=%ROOT%web\scripts\launcher-probe.mjs"
title LogicLens

echo.
echo  LogicLens v2
echo  ------------
echo.

where node >nul 2>nul
if errorlevel 1 goto no_node

rem ---- 1. API (optional) -------------------------------------------------------
rem probe: 0 = LogicLens API answers, 1 = port 8000 free, 2 = another program has it
node "%PROBE%" api >nul 2>nul
set "API_STATE=%errorlevel%"
if "%API_STATE%"=="0" goto api_running
tasklist /fi "WINDOWTITLE eq LogicLens API*" /fo csv /nh 2>nul | find /i "cmd.exe" >nul
if not errorlevel 1 goto api_starting
if "%API_STATE%"=="2" goto api_port_busy
call :find_python
if not defined PY goto no_python
echo  [1/2] Starting the API in a second window: screenshot recognition and AI.
echo        Its first start installs Python packages, 2 to 5 minutes. Leave it open.
start "LogicLens API" /d "%ROOT%backend" cmd /k call run-server.cmd
goto web

:api_running
echo  [1/2] The API is already running.
goto web

:api_starting
echo  [1/2] The API window is already open, so it is not started twice.
goto web

:api_port_busy
echo  [1/2] Port 8000 is used by another program, so the API can't start.
echo        Text analysis still works. Close that program and run this file again.
goto web

:no_python
echo  [1/2] Python 3.11 to 3.13 was not found, so the API is skipped.
echo        Text analysis, all checks, Structured Text and the simulator still work.
echo        For screenshot recognition install Python 3.12 from https://www.python.org
echo        - tick "Add python.exe to PATH" - then run this file again.

rem ---- 2. Web app ----------------------------------------------------------------
:web
echo.
node "%PROBE%" web >nul 2>nul
if not errorlevel 1 goto web_running
tasklist /fi "WINDOWTITLE eq LogicLens web*" /fo csv /nh 2>nul | find /i "cmd.exe" >nul
if not errorlevel 1 goto web_starting
title LogicLens web - http://localhost:5173
cd /d "%ROOT%web"
if not exist "node_modules\.package-lock.json" goto install_web
if exist "node_modules\vite\bin\vite.js" goto run_web

:install_web
echo  [2/2] First start: installing the web app's packages, 1 to 2 minutes...
call npm ci --no-audit --no-fund --loglevel=error
if errorlevel 1 goto npm_failed

:run_web
echo  [2/2] Starting the web app. Your browser opens at http://localhost:5173
echo        Keep this window open while you use LogicLens. Close it to stop.
echo.
node "node_modules\vite\bin\vite.js" --open
goto end

:web_running
echo  [2/2] LogicLens is already running. Opening it in your browser...
start "" "http://localhost:5173/"
timeout /t 4 >nul 2>nul
goto end

:web_starting
echo  [2/2] LogicLens is already starting in another window.
echo        That window opens your browser when it is ready.
timeout /t 6 >nul 2>nul
goto end

:no_node
echo  Node.js was not found.
echo   - Quick look, nothing to install: open LogicLens.html in this folder.
echo   - Full app: install Node.js LTS from https://nodejs.org, then run this file again.
echo.
pause
goto end

:npm_failed
echo.
echo  Installing the packages failed - the messages above say why.
echo  Most often: no internet connection or a company proxy. Fix that and run this file again.
echo.
pause
goto end

rem ---------------------------------------------------------------------------
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
