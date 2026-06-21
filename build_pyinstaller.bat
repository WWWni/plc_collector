@echo on
chcp 936 >nul
echo ============================================================
echo   PLC Collector - PyInstaller Build Script
echo ============================================================
echo.

set OUTPUT_DIR=%~dp0dist\PLC_Collector

echo [1/3] Cleaning old PyInstaller build...
if exist "%OUTPUT_DIR%" rmdir /s /q "%OUTPUT_DIR%"
if exist "%~dp0build" rmdir /s /q "%~dp0build"
echo.

echo [2/3] Building with PyInstaller (using venv)...
call "%~dp0my_env\Scripts\activate.bat"
pyinstaller "%~dp0monitor_app.spec" --clean --noconfirm
if %errorlevel% neq 0 (
    echo Build FAILED!
    pause
    exit /b 1
)
echo.

echo [3/3] Copying config file...
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
copy /Y "%~dp0config.yaml" "%OUTPUT_DIR%\"
echo.

echo ============================================================
echo   Build OK!
echo.
echo   Output: dist\PLC_Collector\
echo.
echo     monitor_app.exe   - PLC Collector (PyInstaller)
echo     config.yaml       - Default config
echo     _internal\        - Runtime deps
echo.
echo   Zip the dist\PLC_Collector folder to distribute.
echo ============================================================
pause
