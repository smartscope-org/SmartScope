@echo off
rem SmartScope has SerialEM start this hidden; SmartScopeLiveImage.log says what it is doing.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0SmartScopeLiveImage.ps1"
