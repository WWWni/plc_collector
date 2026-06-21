@echo on
chcp 936 >nul
echo ============================================================
echo   PLC Collector - Nuitka Build Script
echo ============================================================
echo.

set OUTPUT_DIR=%~dp0dist\PLC_Collector_Nuitka

echo [1/3] Cleaning old Nuitka build...
if exist "%OUTPUT_DIR%\monitor_app.build" rmdir /s /q "%OUTPUT_DIR%\monitor_app.build"
if exist "%OUTPUT_DIR%\monitor_app.dist" rmdir /s /q "%OUTPUT_DIR%\monitor_app.dist"
if exist "%OUTPUT_DIR%\monitor_app.onefile-build" rmdir /s /q "%OUTPUT_DIR%\monitor_app.onefile-build"
if exist "%OUTPUT_DIR%\monitor_app.exe" del /f /q "%OUTPUT_DIR%\monitor_app.exe"
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
echo.

echo [2/3] Building with Nuitka (onefile + MSVC 14.5)...
call "%~dp0my_env\Scripts\activate.bat"

nuitka --onefile ^
       --msvc=14.5 ^
       --enable-plugins=pyside6 ^
       --windows-console-mode=disable ^
       --windows-icon-from-ico="%~dp0favicon.ico" ^
       --include-data-files="%~dp0favicon.ico=favicon.ico" ^
       --include-module=qasync ^
       --include-module=pymodbus ^
       --include-module=pymodbus.client ^
       --include-module=pymysql ^
       --include-module=sqlalchemy.dialects.mysql ^
       --include-module=sqlalchemy.pool ^
       --include-module=sqlalchemy.engine ^
       --nofollow-import-to=tkinter ^
       --nofollow-import-to=matplotlib ^
       --nofollow-import-to=scipy ^
       --nofollow-import-to=IPython ^
       --nofollow-import-to=jupyter ^
       --nofollow-import-to=notebook ^
       --nofollow-import-to=pytest ^
       --output-dir="%OUTPUT_DIR%" ^
       --output-filename=monitor_app.exe ^
       "%~dp0monitor_app.py"

if %errorlevel% neq 0 (
    echo Build FAILED!
    pause
    exit /b 1
)
echo.

echo [3/3] Copying config file...
copy /Y "%~dp0config.yaml" "%OUTPUT_DIR%\"
echo.

echo ============================================================
echo   Build OK!
echo.
echo   Output: dist\PLC_Collector_Nuitka\
echo.
echo     monitor_app.exe   - PLC Collector (Nuitka, native binary)
echo     config.yaml       - Default config
echo.
echo   Zip the dist\PLC_Collector_Nuitka folder to distribute.
echo ============================================================
pause
