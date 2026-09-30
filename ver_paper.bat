@echo off
cd /d "%~dp0"
python paper.py
start "" notepad "paper\ESTADO.md"
