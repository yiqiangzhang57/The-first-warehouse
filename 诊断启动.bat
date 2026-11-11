@echo off
chcp 65001 >nul
cd /d "%~dp0"
python assistant.py
if errorlevel 1 (
  echo.
  echo 浮浮助手启动失败，请将上面的错误信息提供给开发者。
  pause
)
