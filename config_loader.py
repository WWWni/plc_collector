"""
配置文件加载与校验模块
======================
支持多串口服务器架构：每台服务器独立配置 connection / serial / devices。
"""
import os
import uuid
import socket
import yaml
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ConnectionConfig:
    mode: str = "modbus_tcp"
    host: str = "192.168.1.200"
    port: int = 4196
    tcp_timeout: int = 1     # TCP连接超时（秒）


@dataclass
class SerialConfig:
    baudrate: int = 9600
    data_bits: int = 8
    stop_bits: int = 1
    parity: str = "none"


@dataclass
class DeviceConfig:
    slave_addr: int = 1
    name: str = ""
    device_type: str = ""    # 设备类型标识，空字符串表示使用注册表默认类型
    timeout: Optional[float] = None   # None = 使用所属服务器全局默认
    retry: Optional[int] = None       # None = 使用所属服务器全局默认
    server_index: int = 0             # 运行时填充，不写入 yaml


@dataclass
class ServerConfig:
    """单台串口服务器配置（聚合 connection + serial + devices）"""
    name: str = "串口服务器1"
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    devices: List[DeviceConfig] = field(default_factory=list)


@dataclass
class SchedulerConfig:
    interval_seconds: int = 4
    batch_read: bool = True
    timeout: float = 0.3     # Modbus读取超时（秒）
    retry: int = 1           # Modbus读取重试
    retry_delay: float = 0.1  # 重试前等待间隔（秒），RS485超时后短暂等待再重试


@dataclass
class DatabaseConfig:
    engine: str = "mysql"
    host: str = "localhost"
    port: int = 3306
    username: str = "root"
    password: str = ""
    database: str = "plc_data"
    table_name: str = "plc_data"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/collector.log"
    max_bytes: int = 10485760
    backup_count: int = 5


@dataclass
class AppConfig:
    servers: List[ServerConfig] = field(default_factory=list)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    display_config: dict = field(default_factory=dict)  # {device_type: [field_def, ...]}
    collector_id: str = ""  # 采集实例唯一标识，空则自动解析

    @property
    def all_devices(self) -> List[DeviceConfig]:
        """返回所有服务器的扁平化设备列表"""
        result = []
        for srv in self.servers:
            result.extend(srv.devices)
        return result


# ------------------------------------------------------------------
# 解析辅助
# ------------------------------------------------------------------

def _parse_connection(raw: dict) -> ConnectionConfig:
    return ConnectionConfig(
        mode=raw.get("mode", "modbus_tcp"),
        host=raw.get("host", "192.168.1.200"),
        port=raw.get("port", 4196),
        tcp_timeout=raw.get("tcp_timeout", 1),
    )


def _parse_serial(raw: dict) -> SerialConfig:
    return SerialConfig(
        baudrate=raw.get("baudrate", 9600),
        data_bits=raw.get("data_bits", 8),
        stop_bits=raw.get("stop_bits", 1),
        parity=raw.get("parity", "none"),
    )


def _parse_devices(raw_list: list, server_index: int) -> List[DeviceConfig]:
    devices = []
    for dev in raw_list:
        dc = DeviceConfig(
            slave_addr=dev.get("slave_addr", 1),
            name=dev.get("name", ""),
            device_type=dev.get("device_type", ""),
            timeout=dev.get("timeout"),
            retry=dev.get("retry"),
            server_index=server_index,
        )
        if not 1 <= dc.slave_addr <= 128:
            raise ValueError(
                f"从站地址超出范围(1-128): {dc.slave_addr} "
                f"(服务器索引={server_index})"
            )
        devices.append(dc)
    return devices


# ------------------------------------------------------------------
# 主入口
# ------------------------------------------------------------------

def load_config(config_path: str = "config.yaml") -> AppConfig:
    """加载并校验配置文件，返回AppConfig实例"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError("配置文件为空")

    config = AppConfig()

    # ---- 解析服务器列表 ----
    if "servers" in raw and isinstance(raw["servers"], list):
        config.servers = []
        for idx, srv_raw in enumerate(raw["servers"]):
            conn_raw = srv_raw.get("connection", {})
            conn = _parse_connection(conn_raw)
            if conn.mode not in ("tcp_transparent", "modbus_tcp"):
                raise ValueError(f"不支持的连接模式: {conn.mode}")

            serial = _parse_serial(srv_raw.get("serial", {}))
            devices = _parse_devices(
                srv_raw.get("devices", []), server_index=idx
            )

            config.servers.append(ServerConfig(
                name=srv_raw.get("name", f"串口服务器{idx + 1}"),
                connection=conn,
                serial=serial,
                devices=devices,
            ))
    else:
        raise ValueError(
            "配置文件缺少 servers 列表，请参考多服务器配置格式"
        )

    # ---- 解析调度配置 ----
    if "scheduler" in raw:
        sched = raw["scheduler"]
        config.scheduler = SchedulerConfig(
            interval_seconds=sched.get("interval_seconds", 4),
            batch_read=sched.get("batch_read", True),
            timeout=sched.get("timeout", 0.3),
            retry=sched.get("retry", 1),
            retry_delay=sched.get("retry_delay", 0.1),
        )

    # ---- 解析数据库配置 ----
    if "database" in raw:
        db = raw["database"]
        config.database = DatabaseConfig(
            engine=db.get("engine", "mysql"),
            host=db.get("host", "localhost"),
            port=db.get("port", 3306),
            username=db.get("username", "root"),
            password=db.get("password", ""),
            database=db.get("database", "plc_data"),
            table_name=db.get("table_name", "plc_data"),
        )
        if config.database.engine not in ("mysql", "postgresql"):
            raise ValueError(f"不支持的数据库引擎: {config.database.engine}")

    # ---- 解析日志配置 ----
    if "logging" in raw:
        log = raw["logging"]
        config.logging = LoggingConfig(
            level=log.get("level", "INFO"),
            file=log.get("file", "logs/collector.log"),
            max_bytes=log.get("max_bytes", 10485760),
            backup_count=log.get("backup_count", 5),
        )

    # ---- 解析展示配置 ----
    if "display_config" in raw and isinstance(raw["display_config"], dict):
        config.display_config = raw["display_config"]

    # ---- 解析采集实例 ID ----
    config.collector_id = _resolve_collector_id(
        raw.get("collector_id", ""), config_path
    )

    return config


def _resolve_collector_id(configured_id: str, config_path: str) -> str:
    """
    解析采集实例唯一标识

    优先级: config.yaml 手动配置 > collector.id 文件 > 自动生成 UUID
    """
    # 1. config.yaml 中手动配置
    if configured_id and configured_id.strip():
        return configured_id.strip()

    # 2. 从 collector.id 文件读取（上次自动生成的）
    id_file = os.path.join(os.path.dirname(os.path.abspath(config_path)), "collector.id")
    if os.path.exists(id_file):
        try:
            with open(id_file, "r", encoding="utf-8") as f:
                saved_id = f.read().strip()
            if saved_id:
                return saved_id
        except Exception:
            pass

    # 3. 自动生成 UUID 并持久化
    generated = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    try:
        with open(id_file, "w", encoding="utf-8") as f:
            f.write(generated)
    except Exception:
        pass
    return generated


def get_db_url(db_config: DatabaseConfig) -> str:
    """根据数据库配置生成SQLAlchemy连接URL"""
    if db_config.engine == "mysql":
        return (
            f"mysql+pymysql://{db_config.username}:{db_config.password}"
            f"@{db_config.host}:{db_config.port}/{db_config.database}"
            f"?charset=utf8mb4"
        )
    elif db_config.engine == "postgresql":
        return (
            f"postgresql+psycopg2://{db_config.username}:{db_config.password}"
            f"@{db_config.host}:{db_config.port}/{db_config.database}"
        )
    else:
        raise ValueError(f"不支持的数据库引擎: {db_config.engine}")
