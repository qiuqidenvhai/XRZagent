@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title XianRenZhang Agent
python terminal.py
pause
