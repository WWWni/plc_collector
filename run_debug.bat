@echo off
chcp 65001 >nul
title PLC Collector - Debug

echo ============================================================
echo   PLC Collector - Debug Mode
echo ============================================================
echo.

REM 激活虚拟环境
call "%~dp0my_env\Scripts\activate.bat"

REM 默认启动监控主程序，支持传入额外参数
REM 用法:
REM   run_debug.bat                  -> 正常模式启动
REM   run_debug.bat --test           -> 模拟模式（随机测试数据）
REM   run_debug.bat -c my_config.yaml -> 指定配置文件
if "%~1"=="" (
    python "%~dp0monitor_app.py"
) else (
    python "%~dp0monitor_app.py" %*
)

echo.
echo 程序已退出，按任意键关闭窗口...
pause >nul
