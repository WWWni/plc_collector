"""
SQLAlchemy ORM 数据模型
========================
两张表:
- device_type_def: 设备类型定义（协议/寄存器/解析规则/显示配置）
- plc_data: 统一采集数据表（所有设备类型共用，字段值存 JSON）

支持 MySQL 5.7+（JSON 列类型）和 PostgreSQL。
"""

import json
from datetime import datetime
from sqlalchemy import (
    Column, BigInteger, SmallInteger, Integer,
    String, DateTime, Text, Index, Enum,
)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase


# ============================================================
# JSON 列兼容类型 (MySQL 原生 JSON / PostgreSQL JSON / SQLite Text)
# ============================================================

class JSONType(TypeDecorator):
    """跨引擎 JSON 列类型"""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value, ensure_ascii=False)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            if isinstance(value, str):
                return json.loads(value)
            return value  # 原生 JSON 类型已自动解析
        return None


class Base(DeclarativeBase):
    pass


# ============================================================
# 设备类型定义表 (device_type_def)
# ============================================================

class DeviceTypeDef(Base):
    """
    设备类型定义表

    每个设备类型一行，存储该类型的所有协议配置、解析规则、显示定义。
    新增设备类型只需在此表中插入新行，采集程序无需改代码。
    """
    __tablename__ = "device_type_def"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_type = Column(String(50), unique=True, nullable=False)  # 类型标识
    display_name = Column(String(100), nullable=False)             # 显示名称
    default_name_prefix = Column(String(20), default="设备")       # 设备命名前缀

    # ---- 寄存器读取方式 ----
    read_mode = Column(
        Enum("contiguous", "grouped", name="read_mode_enum"),
        nullable=False, default="contiguous",
    )
    reg_base = Column(Integer, nullable=True)   # 连续读取: 基地址
    reg_count = Column(Integer, nullable=True)  # 连续读取: 寄存器数量
    read_groups = Column(JSONType, nullable=True)  # 分组读取: [{"start":N,"count":N},...]

    # ---- 寄存器定义 ----
    # [{"idx":0,"name":"current_gear","addr":2202,"desc":"档位"}, ...]
    registers = Column(JSONType, nullable=False)

    # ---- 解析规则 ----
    # [{"field":"speed","op":"scale","src_idx":16,"factor":0.1}, ...]
    parse_rules = Column(JSONType, nullable=False)

    # ---- 位域定义 ----
    # [{"src_idx":14,"byte":"high","prefix":"rs_","bits":{"7":{"name":"force","label":"强迫"},...}}]
    bit_fields = Column(JSONType, nullable=True)

    # ---- 运行模式判断 ----
    # [{"field":"rs_running","mode":"running"}, {"field":"rs_jogging","mode":"jogging"}, ...]
    run_mode_rules = Column(JSONType, nullable=True)

    # ---- 故障名称映射 ----
    # [{"key":"ft_overspeed","label":"超速"}, ...]
    fault_names = Column(JSONType, nullable=True)

    # ---- UI 显示配置 ----
    # [{"key":"speed","label":"转速","unit":"rpm","format":".1f"}, ...]
    display_fields = Column(JSONType, nullable=False)

    # [{"key":"fabric_count","label":"织布数"}]  
    chart_fields = Column(JSONType, nullable=True)

    # {"running":{"color":"#4caf50","text":"运行中"}, "stopped":{...}, ...}
    status_map = Column(JSONType, nullable=True)

    # ---- 值映射 ----
    # {"unit_map":{"0":"米","1":"码"}, "mode_map":{"0":"计长","1":"速度"}}
    value_mappings = Column(JSONType, nullable=True)

    def __repr__(self):
        return f"<DeviceTypeDef({self.device_type!r}, {self.display_name!r})>"


# ============================================================
# 统一采集数据表 (plc_data)
# ============================================================

class PlcData(Base):
    """
    统一采集数据表 — 所有设备类型共用

    field_data 列存储 JSON 格式的采集字段值。
    """
    __tablename__ = "plc_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # 元数据
    timestamp = Column(DateTime, nullable=False, default=datetime.now, index=True)
    collector_id = Column(String(50), nullable=False, default="", index=True)
    server_index = Column(SmallInteger, nullable=False, default=0, index=True)
    slave_addr = Column(SmallInteger, nullable=False, index=True)
    device_name = Column(String(50), nullable=True)
    device_type = Column(String(50), nullable=False)

    # 采集数据 (JSON)
    field_data = Column(JSONType, nullable=True)

    # 运行模式
    run_mode = Column(String(20), nullable=True)

    # 故障日志 (JSON)
    fault_log = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_plc_server_device_time", "server_index", "slave_addr", "timestamp"),
    )

    def __repr__(self):
        return (
            f"<PlcData(id={self.id}, addr={self.slave_addr}, "
            f"type={self.device_type}, time={self.timestamp})>"
        )


# 所有模型列表 (用于 create_all)
ALL_MODELS = [DeviceTypeDef, PlcData]
