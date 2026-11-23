@echo off
rem Install (or update) Linux Island for this user. "install.cmd -Uninstall" removes it.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
