@echo off
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo حصلت مشكلة. لو الرسالة فوق فيها "python is not recognized"، لازم تنزّل بايثون الأول (شوف README.txt).
  pause
)
