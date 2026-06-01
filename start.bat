@echo off
chcp 936 >nul 2>&1
title оихкуф Agent
cd /d "%~dp0"
python terminal.py %*
