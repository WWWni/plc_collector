"""
设备类型注册表
==============
集中管理所有支持的设备类型，提供统一的注册、查询接口。
设备类型定义存储在数据库 device_type_def 表中，启动时通过 load_from_db() 加载。
数据库不可用时回退到本地缓存文件（上次成功加载的快照）。
"""

import json
import logging
import os
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("plc_collector.device_types")

# 注册表: device_type_key -> GenericParser 实例
_REGISTRY: Dict[str, object] = {}


def register(parser) -> None:
    """
    注册一个 GenericParser 实例

    Args:
        parser: GenericParser 实例，必须包含 DEVICE_TYPE 属性
    """
    device_type = parser.DEVICE_TYPE
    if not device_type:
        raise ValueError(f"解析器缺少 DEVICE_TYPE: {parser}")

    required = ["parse_registers", "get_run_mode", "get_active_faults",
                 "DISPLAY_FIELDS"]
    for attr in required:
        if not hasattr(parser, attr):
            raise ValueError(f"设备类型 {device_type!r} 缺少属性: {attr}")

    has_contiguous = hasattr(parser, "REG_BASE") and hasattr(parser, "REG_COUNT")
    has_groups = hasattr(parser, "READ_GROUPS")
    if not has_contiguous and not has_groups:
        raise ValueError(
            f"设备类型 {device_type!r} 缺少寄存器读取定义"
        )

    if device_type in _REGISTRY:
        logger.debug(f"设备类型 {device_type!r} 已存在，将覆盖")

    _REGISTRY[device_type] = parser
    logger.info(f"注册设备类型: {device_type} ({parser.DISPLAY_NAME})")


def register_from_dict(type_def: dict) -> None:
    """
    从字典创建设备类型并注册

    Args:
        type_def: device_type_def 行数据的字典
    """
    from protocol.generic_parser import GenericParser
    parser = GenericParser(type_def)
    register(parser)


def get(device_type: str):
    """获取设备类型解析器"""
    if device_type not in _REGISTRY:
        raise KeyError(
            f"未注册的设备类型: {device_type!r}，"
            f"可用: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[device_type]


def get_safe(device_type: str, default_type: str = ""):
    """安全获取，未知类型回退到默认"""
    result = _REGISTRY.get(device_type)
    if result is None:
        fallback = default_type or get_default_type()
        result = _REGISTRY.get(fallback)
    if result is None and _REGISTRY:
        result = next(iter(_REGISTRY.values()))
    return result


def list_types() -> List[Tuple[str, str]]:
    """列出所有已注册的设备类型: [(key, display_name), ...]"""
    return [
        (key, parser.DISPLAY_NAME)
        for key, parser in _REGISTRY.items()
    ]


def get_default_type() -> str:
    """获取默认设备类型（注册表中的第一个）"""
    if _REGISTRY:
        return next(iter(_REGISTRY))
    return ""


def get_default_name_prefix(device_type: str) -> str:
    """获取设备类型的默认名称前缀"""
    parser = _REGISTRY.get(device_type)
    if parser:
        return getattr(parser, "DEFAULT_NAME_PREFIX", "设备")
    return "设备"


# ============================================================
# 从数据库加载
# ============================================================

def load_from_db(session_factory) -> int:
    """
    从 device_type_def 表加载所有设备类型定义

    Args:
        session_factory: SQLAlchemy sessionmaker 实例

    Returns:
        加载的设备类型数量
    """
    from storage.models import DeviceTypeDef

    try:
        with session_factory() as session:
            rows = session.query(DeviceTypeDef).all()
            if not rows:
                return 0

            count = 0
            for row in rows:
                type_def = {
                    "device_type": row.device_type,
                    "display_name": row.display_name,
                    "default_name_prefix": row.default_name_prefix,
                    "read_mode": row.read_mode,
                    "reg_base": row.reg_base,
                    "reg_count": row.reg_count,
                    "read_groups": row.read_groups,
                    "read_function": getattr(row, "read_function", None) or "holding",
                    "registers": row.registers,
                    "parse_rules": row.parse_rules,
                    "bit_fields": row.bit_fields,
                    "run_mode_rules": row.run_mode_rules,
                    "fault_names": row.fault_names,
                    "display_fields": row.display_fields,
                    "status_map": row.status_map,
                    "value_mappings": row.value_mappings,
                }
                register_from_dict(type_def)
                count += 1

            logger.info(f"从数据库加载 {count} 个设备类型定义")
            return count

    except Exception as e:
        logger.warning(f"从数据库加载设备类型失败: {e}")
        return 0


# ============================================================
# 本地缓存（DB 不可用时的回退）
# ============================================================

_CACHE_FILENAME = "device_type_cache.json"


def _get_cache_path(cache_dir: str = None) -> str:
    """获取缓存文件路径，默认与 config.yaml 同目录"""
    if cache_dir is None:
        cache_dir = os.getcwd()
    return os.path.join(cache_dir, _CACHE_FILENAME)


def save_cache(cache_dir: str = None) -> None:
    """
    将当前注册表中的设备类型定义序列化保存到本地缓存文件

    Args:
        cache_dir: 缓存文件存放目录，默认为当前工作目录
    """
    if not _REGISTRY:
        return

    cache_path = _get_cache_path(cache_dir)
    try:
        defs = []
        for key, parser in _REGISTRY.items():
            type_def = {
                "device_type": parser.DEVICE_TYPE,
                "display_name": parser.DISPLAY_NAME,
                "default_name_prefix": parser.DEFAULT_NAME_PREFIX,
                "read_mode": parser._read_mode,
                "reg_base": getattr(parser, "REG_BASE", None),
                "reg_count": getattr(parser, "REG_COUNT", None),
                "read_groups": getattr(parser, "READ_GROUPS", None),
                "read_function": getattr(parser, "READ_FUNCTION", "holding"),
                "registers": parser._registers,
                "parse_rules": parser._parse_rules,
                "bit_fields": parser._bit_fields or None,
                "run_mode_rules": parser._run_mode_rules,
                "fault_names": parser._fault_names or None,
                "display_fields": parser.DISPLAY_FIELDS,
                "status_map": parser.STATUS_MAP,
                "value_mappings": parser._value_mappings or None,
            }
            defs.append(type_def)

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(defs, f, ensure_ascii=False, indent=2)

        logger.info(f"设备类型缓存已保存: {cache_path} ({len(defs)} 个类型)")

    except Exception as e:
        logger.warning(f"保存设备类型缓存失败: {e}")


def load_cache(cache_dir: str = None) -> int:
    """
    从本地缓存文件加载设备类型定义（DB 不可用时的回退）

    Args:
        cache_dir: 缓存文件所在目录，默认为当前工作目录

    Returns:
        加载的设备类型数量，0 表示缓存不存在或加载失败
    """
    cache_path = _get_cache_path(cache_dir)
    if not os.path.exists(cache_path):
        logger.info("无本地设备类型缓存")
        return 0

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            defs = json.load(f)

        count = 0
        for type_def in defs:
            try:
                register_from_dict(type_def)
                count += 1
            except Exception as e:
                logger.error(f"从缓存加载失败 ({type_def.get('device_type')}): {e}")

        logger.info(f"从本地缓存加载 {count} 个设备类型定义")
        return count

    except Exception as e:
        logger.warning(f"读取设备类型缓存失败: {e}")
        return 0
