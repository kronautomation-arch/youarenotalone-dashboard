@echo off
REM Ejecuta main.py manualmente en Windows con venv activado
cd /d "%~dp0"
if not exist venv (
  echo Creando venv...
  python -m venv venv
)
call venv\Scripts\activate.bat
pip install -q -r requirements.txt
python main.py
pause
