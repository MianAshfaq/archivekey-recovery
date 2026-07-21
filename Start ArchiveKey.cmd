@echo off
setlocal
cd /d "%~dp0"
pythonw app.py
if errorlevel 1 (
  echo ArchiveKey could not start. Confirm Python 3.11 or newer is installed.
  pause
)
