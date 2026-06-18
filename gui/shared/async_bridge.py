"""
asyncio与Qt事件循环桥接
========================
使用qasync将Qt事件循环替换为asyncio兼容的事件循环，
使asyncio协程和Qt信号/槽可以在同一个线程中协同工作。
"""

import sys
import asyncio
import logging

logger = logging.getLogger("plc_collector.gui.bridge")


def setup_async_qt():
    """
    初始化asyncio+Qt混合事件循环

    必须在QApplication创建之后、event loop启动之前调用。

    Returns:
        (QApplication, qasync.QEventLoop) 元组
    """
    from PySide6.QtWidgets import QApplication

    # 创建QApplication（如果还没有）
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # 创建qasync事件循环
    try:
        from qasync import QEventLoop
        loop = QEventLoop(app)
        asyncio.set_event_loop(loop)
        logger.info("qasync事件循环初始化成功")
        return app, loop
    except ImportError:
        logger.error("qasync未安装，请运行: pip install qasync")
        raise


def run_async_qt_app(setup_func):
    """
    启动asyncio+Qt混合应用

    Args:
        setup_func: async函数，接收事件循环，负责创建窗口和启动业务逻辑
    """
    app, loop = setup_async_qt()

    try:
        with loop:
            loop.create_task(setup_func())
            loop.run_forever()
    except KeyboardInterrupt:
        logger.info("用户中断，应用退出")
    finally:
        asyncio.set_event_loop(None)
