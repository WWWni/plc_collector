"""PLC面板数据采集系统 — 统一启动入口
========================================
采集监控 + 配置管理一体化，内置配置按钮可随时打开配置界面。

使用方法:
    python monitor_app.py                    # 正常模式（连接真实设备）
    python monitor_app.py --test             # 模拟模式（随机测试数据，无需设备）
    python monitor_app.py -c my_config.yaml  # 指定配置文件

支持多串口服务器架构：每台ZLAN5143D独立传输层。
"""

import sys
import os
import asyncio
import argparse
import logging

# 确保项目根目录在sys.path中（开发模式兼容）
_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

from utils.paths import get_resource_path, get_app_dir

logger = logging.getLogger("plc_collector.app")


def create_transports(config):
    """根据配置为每台服务器创建传输层实例，返回列表"""
    from config_loader import ServerConfig
    from transport.tcp_transparent import TcpTransparentTransport
    from transport.modbus_tcp import ModbusTcpTransport

    # 从 scheduler 获取全局 Modbus 超时/重试
    modbus_timeout = config.scheduler.timeout
    modbus_retry = config.scheduler.retry

    transports = []
    for srv in config.servers:
        mode = srv.connection.mode
        if mode == "tcp_transparent":
            t = TcpTransparentTransport(
                host=srv.connection.host,
                port=srv.connection.port,
                tcp_timeout=srv.connection.tcp_timeout,
                tcp_retry=srv.connection.tcp_retry,
                modbus_timeout=modbus_timeout,
                modbus_retry=modbus_retry,
            )
        elif mode == "modbus_tcp":
            t = ModbusTcpTransport(
                host=srv.connection.host,
                port=srv.connection.port or 502,
                tcp_timeout=srv.connection.tcp_timeout,
                tcp_retry=srv.connection.tcp_retry,
                modbus_timeout=modbus_timeout,
                modbus_retry=modbus_retry,
            )
        else:
            raise ValueError(f"不支持的连接模式: {mode}")
        transports.append(t)
    return transports


async def async_setup(window, config, test_mode: bool):
    """异步初始化：仅模拟模式自动启动，正常模式等待用户点击开始采集"""
    import logging as _logging
    _logger = _logging.getLogger("plc_collector.app")

    if test_mode:
        window.start_simulation()
        _logger.info("采集程序已启动 — 模拟模式")
    else:
        _logger.info("采集程序已启动 — 等待用户点击\"开始采集\"")


def main():
    default_config = get_resource_path("config.yaml")

    parser = argparse.ArgumentParser(
        description="PLC面板数据采集系统",
    )
    parser.add_argument(
        "-c", "--config",
        default=default_config,
        help=f"配置文件路径 (默认: {default_config})",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="模拟模式: 生成随机测试数据，无需连接真实设备",
    )
    args = parser.parse_args()

    # 加载配置
    from config_loader import load_config
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"配置加载失败: {e}")
        sys.exit(1)

    # 设置日志 — 日志文件放在exe同级目录的logs/下
    from utils.logger import setup_logger
    log_file = config.logging.file
    if not os.path.isabs(log_file):
        log_file = os.path.join(get_app_dir(), log_file)
    setup_logger(
        level=config.logging.level,
        log_file=log_file,
        max_bytes=config.logging.max_bytes,
        backup_count=config.logging.backup_count,
    )

    # 尽早初始化数据库并加载设备类型定义（确保配置UI能看到DB中的设备类型）
    db_manager = None
    config_dir = os.path.dirname(os.path.abspath(args.config))
    try:
        from storage.db_manager import DatabaseManager
        from protocol.device_types import (
            load_from_db as load_device_types_from_db,
            save_cache,
        )
        db_manager = DatabaseManager(config.database)
        db_manager.initialize()
        n = load_device_types_from_db(db_manager.session_factory)
        if n > 0:
            save_cache(config_dir)
        logger.info(f"数据库初始化成功，从DB加载 {n} 个设备类型定义")
    except Exception as e:
        logger.warning(f"数据库初始化失败，尝试从本地缓存加载: {e}")
        from protocol.device_types import load_cache
        n = load_cache(config_dir)
        if n > 0:
            logger.info(f"从缓存恢复 {n} 个设备类型定义")
        else:
            logger.warning("无可用缓存，程序将以无设备类型模式运行")
        db_manager = None

    # 初始化Qt + asyncio混合事件循环
    from gui.shared.async_bridge import setup_async_qt
    from gui.shared.styles import MAIN_STYLE

    app, loop = setup_async_qt()
    app.setStyleSheet(MAIN_STYLE)

    # 立即创建并显示主窗口（传输层和数据库延迟初始化）
    from gui.monitor.main_window import MonitorMainWindow
    window = MonitorMainWindow(
        config=config,
        transports=[],
        db_manager=db_manager,
        config_path=args.config,
        transport_factory=create_transports,
    )
    window.show()

    # 启动事件循环（模拟模式自动启动，正常模式等待用户操作）
    with loop:
        loop.create_task(async_setup(window, config, args.test))
        loop.run_forever()


if __name__ == "__main__":
    main()
