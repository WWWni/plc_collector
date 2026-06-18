"""
路径解析工具
============
兼容开发模式和PyInstaller打包模式的路径解析。

打包后 sys.frozen=True, sys.executable 指向exe路径,
__file__ 指向 _MEIPASS 临时目录（仅适用于模块导入）。
"""

import sys
import os


def is_frozen() -> bool:
    """判断是否在PyInstaller打包模式下运行"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_app_dir() -> str:
    """
    获取应用程序所在目录

    - 开发模式: 返回项目根目录 (plc_collector/)
    - 打包模式: 返回exe所在目录
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    # 开发模式: 本文件在 utils/paths.py, 项目根目录在上一级
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path: str) -> str:
    """
    获取资源文件的绝对路径（相对于应用程序目录）

    Args:
        relative_path: 相对于app目录的路径，如 "config.yaml" 或 "logs/collector.log"

    Returns:
        绝对路径字符串
    """
    return os.path.join(get_app_dir(), relative_path)
