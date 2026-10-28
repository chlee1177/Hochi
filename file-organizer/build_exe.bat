@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller==6.16.0
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name FileNest --paths .. app.py
if errorlevel 1 goto failed
echo Build complete: dist\FileNest.exe
pause
exit /b 0
:failed
echo Build failed. Check the output above.
pause
exit /b 1
