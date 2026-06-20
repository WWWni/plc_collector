@echo on
chcp 936 >nul
echo ============================================================
echo   PLC Collector - Build Script (Unified App)
echo ============================================================
echo.

set APP_DIR=PLC_Collector

echo [1/3] Cleaning old build...
if exist "%~dp0dist\%APP_DIR%" rmdir /s /q "%~dp0dist\%APP_DIR%"
if exist "%~dp0build" rmdir /s /q "%~dp0build"
echo.

echo [2/3] Building unified app (using venv)...
call "%~dp0my_env\Scripts\activate.bat"
pyinstaller "%~dp0monitor_app.spec" --clean --noconfirm
if %errorlevel% neq 0 (
    echo Build FAILED!
    pause
    exit /b 1
)
echo.

echo [3/3] Copying config file...
copy /Y "%~dp0config.yaml" "%~dp0dist\%APP_DIR%\"
echo.

echo ============================================================
echo   Build OK!
echo.
echo   Output: dist\%APP_DIR%\
echo.
echo     monitor_app.exe   - PLC Collector (unified)
echo     config.yaml       - Default config
echo     _internal\        - Runtime deps
echo.
echo   Zip the dist\%APP_DIR% folder to distribute.
echo ============================================================
pause
