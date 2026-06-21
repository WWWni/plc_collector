"""
路径解析工具
============
兼容开发模式和打包模式（PyInstaller / Nuitka）的路径解析。

- PyInstaller: sys.frozen=True, sys._MEIPASS=临时目录, sys.executable=exe路径
- Nuitka standalone: sys.frozen=True, sys.executable=exe路径
- Nuitka onefile: sys.frozen=True, sys.executable=临时目录, __compiled__.containing_dir=exe目录
"""

import sys
import os


def is_frozen() -> bool:
    """判断是否在打包模式下运行（兼容 PyInstaller 和 Nuitka）"""
    if getattr(sys, 'frozen', False):
        return True
    return False


def _is_nuitka_onefile() -> bool:
    """判断是否为 Nuitka onefile 模式"""
    # Nuitka onefile: sys.executable 指向临时目录，而非原始 exe 位置
    # __compiled__ 对象在 Nuitka 编译后的所有模块中可用
    try:
        compiled = globals().get("__compiled__")
        if compiled is not None:
            return hasattr(compiled, "containing_dir")
    except Exception:
        pass
    return False


def get_app_dir() -> str:
    """
    获取应用程序所在目录

    - 开发模式: 返回项目根目录 (plc_collector/)
    - PyInstaller: 返回 exe 所在目录
    - Nuitka standalone: 返回 exe 所在目录
    - Nuitka onefile: 通过 __compiled__.containing_dir 返回 exe 所在目录
    """
    # Nuitka onefile 模式: sys.executable 指向临时目录，需用 __compiled__
    if _is_nuitka_onefile():
        return globals()["__compiled__"].containing_dir

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
