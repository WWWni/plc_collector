"""
PLC面板数据采集系统 — 主程序入口
==================================

使用方法:
    python main.py                    # 使用默认配置文件 config.yaml
    python main.py -c my_config.yaml  # 指定配置文件
    python main.py --test             # 测试模式（不写数据库，仅打印采集数据）

支持多串口服务器架构：每台ZLAN5143D独立配置，设备按服务器分组采集。
"""

import asyncio
import argparse
import signal
import sys
import os
from typing import List

# 确保项目根目录在sys.path中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import load_config, AppConfig, ServerConfig
from utils.logger import setup_logger
from transport.base import TransportBase
from transport.tcp_transparent import TcpTransparentTransport
from transport.modbus_tcp import ModbusTcpTransport
from collector.scheduler import CollectorScheduler
from storage.db_manager import DatabaseManager
from protocol.device_types import load_from_db as load_device_types_from_db


def create_transport_for_server(server: ServerConfig, modbus_timeout: float, modbus_retry: int, modbus_retry_delay: float = 0.1) -> TransportBase:
    """根据单台服务器配置创建对应的传输层实例"""
    mode = server.connection.mode

    if mode == "tcp_transparent":
        return TcpTransparentTransport(
            host=server.connection.host,
            port=server.connection.port,
            tcp_timeout=server.connection.tcp_timeout,
            modbus_timeout=modbus_timeout,
            modbus_retry=modbus_retry,
        )
    elif mode == "modbus_tcp":
        return ModbusTcpTransport(
            host=server.connection.host,
            port=server.connection.port or 502,
            tcp_timeout=server.connection.tcp_timeout,
            modbus_timeout=modbus_timeout,
            modbus_retry=modbus_retry,
            modbus_retry_delay=modbus_retry_delay,
        )
    else:
        raise ValueError(f"不支持的连接模式: {mode}")


async def on_data_to_db(db_manager: DatabaseManager, data_list: List[dict]):
    """数据采集回调 — 写入数据库"""
    try:
        count = db_manager.batch_insert(data_list)
        if count > 0:
            print(
                f"  [{data_list[0]['timestamp'].strftime('%H:%M:%S')}] "
                f"已写入 {count} 条记录"
            )
    except Exception as e:
        print(f"  数据库写入失败: {e}")


async def on_data_print(data_list: List[dict]):
    """数据采集回调 — 仅打印（测试模式）"""
    from protocol.device_types import get_safe

    for data in data_list:
        ts = data["timestamp"].strftime("%H:%M:%S")
        name = data["device_name"]
        srv = data.get("server_name", "")
        dev_type = data.get("device_type", "")
        print(f"\n{'='*50}")
        print(f"  [{ts}] {srv} / {name} (地址={data['slave_addr']}, 类型={dev_type})")
        print(f"{'='*50}")
        print(f"  运行状态:   {data.get('run_mode', 'unknown')}")

        # 通用: 打印所有解析出的字段 (跳过元数据键)
        skip = {"timestamp", "slave_addr", "device_name", "device_type",
                "server_index", "server_name", "run_mode", "active_faults",
                "fault_log"}
        for key, value in data.items():
            if key in skip:
                continue
            if isinstance(value, float):
                print(f"  {key}: {value:.2f}")
            elif isinstance(value, bool):
                if value:
                    print(f"  {key}: ✓")
            else:
                print(f"  {key}: {value}")

        if data.get("active_faults"):
            print(f"  当前故障:   {', '.join(data['active_faults'])}")
        print()


async def run(config: AppConfig, test_mode: bool = False, config_dir: str = None):
    """主运行逻辑"""
    logger = setup_logger(
        level=config.logging.level,
        log_file=config.logging.file if not test_mode else None,
        max_bytes=config.logging.max_bytes,
        backup_count=config.logging.backup_count,
    )

    total_devices = sum(len(s.devices) for s in config.servers)

    print("=" * 60)
    print("  PLC面板数据采集系统")
    print("=" * 60)
    print(f"  服务器数量: {len(config.servers)}")
    for idx, srv in enumerate(config.servers):
        print(
            f"    [{idx}] {srv.name}  "
            f"{srv.connection.mode}  "
            f"{srv.connection.host}:{srv.connection.port}  "
            f"{len(srv.devices)}台设备"
        )
    print(f"  设备总数:   {total_devices}")
    print(f"  采集间隔:   {config.scheduler.interval_seconds}s")
    print(f"  运行模式:   {'测试模式(不写库)' if test_mode else '正常模式'}")
    print("=" * 60)
    print()

    # 为每台服务器创建独立的传输层
    modbus_timeout = config.scheduler.timeout
    modbus_retry = config.scheduler.retry
    modbus_retry_delay = config.scheduler.retry_delay
    transports: List[TransportBase] = []
    for srv in config.servers:
        try:
            t = create_transport_for_server(srv, modbus_timeout, modbus_retry, modbus_retry_delay)
            transports.append(t)
        except Exception as e:
            print(f"  传输层创建失败 [{srv.name}]: {e}")
            sys.exit(1)

    # 创建数据库管理器（非测试模式）
    db_manager = None
    if not test_mode:
        db_manager = DatabaseManager(config.database, collector_id=config.collector_id)
        try:
            db_manager.initialize()
            print(f"  数据库连接成功: {config.database.engine}://{config.database.host}/{config.database.database}")
            # 从数据库加载设备类型定义到内存注册表
            n_types = load_device_types_from_db(db_manager.session_factory)
            if n_types > 0:
                from protocol.device_types import save_cache
                save_cache(config_dir)
            print(f"  已加载 {n_types} 个设备类型定义")
        except Exception as e:
            print(f"  数据库初始化失败: {e}")
            from protocol.device_types import load_cache
            n = load_cache(config_dir)
            if n > 0:
                print(f"  从本地缓存恢复 {n} 个设备类型定义")
            else:
                print("  无可用缓存，切换为测试模式...")
                test_mode = True

    # 创建数据回调
    if test_mode:
        on_data = on_data_print
    else:
        async def _on_data(data_list):
            await on_data_to_db(db_manager, data_list)
        on_data = _on_data

    # 创建调度器
    scheduler = CollectorScheduler(
        config=config,
        transports=transports,
        on_data=on_data,
    )

    # 信号处理（优雅退出）
    stop_event = asyncio.Event()

    def _signal_handler():
        print("\n收到退出信号，正在停止...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows不支持add_signal_handler
            pass

    # 启动采集
    try:
        await scheduler.start()

        # 等待退出信号
        if hasattr(signal, "SIGINT"):
            try:
                await stop_event.wait()
            except KeyboardInterrupt:
                pass
        else:
            # Windows备用方案
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                pass

    except KeyboardInterrupt:
        pass

    finally:
        print("\n正在停止采集...")
        await scheduler.stop()
        scheduler.print_stats()

        if db_manager:
            stats = db_manager.get_stats()
            print(f"  数据库统计: {stats.get('total_records', 0)} 条记录")
            db_manager.close()

        print("程序已退出")


def main():
    parser = argparse.ArgumentParser(
        description="PLC面板数据采集系统（多串口服务器）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                    使用默认config.yaml启动采集
  python main.py -c myconfig.yaml   指定配置文件
  python main.py --test             测试模式（仅打印，不写库）
  python main.py --test -c dev.yaml 指定配置文件的测试模式
        """,
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="配置文件路径 (默认: config.yaml)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="测试模式: 不写入数据库，仅打印采集数据",
    )

    args = parser.parse_args()

    # 加载配置
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"配置加载失败: {e}")
        sys.exit(1)

    # 运行主程序
    config_dir = os.path.dirname(os.path.abspath(args.config))
    try:
        asyncio.run(run(config, test_mode=args.test, config_dir=config_dir))
    except KeyboardInterrupt:
        print("\n用户中断，程序退出")


if __name__ == "__main__":
    main()
