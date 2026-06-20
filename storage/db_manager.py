"""
数据库管理器
=============
两张表: device_type_def (设备类型定义) + plc_data (统一采集数据)。
支持 MySQL 5.7+ 和 PostgreSQL。
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from config_loader import DatabaseConfig, get_db_url
from storage.models import Base, PlcData, DeviceTypeDef, ALL_MODELS


logger = logging.getLogger("plc_collector.storage.db")


class DatabaseManager:
    """数据库管理器（统一 plc_data 表）"""

    def __init__(self, db_config: DatabaseConfig, collector_id: str = ""):
        self._config = db_config
        self._collector_id = collector_id
        self._engine = None
        self._session_factory = None

    @property
    def session_factory(self):
        """公开 session_factory 供外部使用（如 device_types.load_from_db）"""
        return self._session_factory

    def initialize(self):
        """初始化数据库引擎、建表、填充种子数据"""
        url = get_db_url(self._config)

        engine_kwargs = {
            "pool_size": 5,
            "max_overflow": 10,
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "echo": False,
        }
        if self._config.engine == "mysql":
            engine_kwargs["poolclass"] = QueuePool

        self._engine = create_engine(url, **engine_kwargs)
        Base.metadata.create_all(self._engine)

        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False
        )

        logger.info(
            f"数据库初始化成功: {self._config.engine}://"
            f"{self._config.host}:{self._config.port}/{self._config.database}"
        )

    # ============================================================
    # 采集数据读写
    # ============================================================

    def batch_insert(self, data_list: List[dict]) -> int:
        """
        批量插入采集数据到 plc_data 表

        Args:
            data_list: 采集数据字典列表

        Returns:
            成功插入的记录数
        """
        if not data_list:
            return 0

        if not self._session_factory:
            raise RuntimeError("数据库未初始化，请先调用 initialize()")

        from storage.fault_events import attach_fault_events
        attach_fault_events(data_list)

        session = self._session_factory()
        inserted = 0

        try:
            records = []
            for data in data_list:
                # 构建 field_data: 所有非元数据的字段
                field_data = {}
                skip_keys = {
                    "timestamp", "server_index", "slave_addr",
                    "device_name", "device_type", "server_name",
                    "run_mode", "active_faults", "fault_log",
                }
                for k, v in data.items():
                    if k not in skip_keys:
                        field_data[k] = v

                record = PlcData(
                    timestamp=data.get("timestamp", datetime.now()),
                    collector_id=self._collector_id,
                    server_index=data.get("server_index", 0),
                    slave_addr=data.get("slave_addr", 0),
                    device_name=data.get("device_name", ""),
                    device_type=data.get("device_type", "unknown"),
                    field_data=field_data,
                    run_mode=data.get("run_mode"),
                    fault_log=data.get("fault_log"),
                )
                records.append(record)

            session.bulk_save_objects(records)
            inserted = len(records)
            session.commit()
            logger.debug(f"批量写入 {inserted} 条记录")

        except Exception as e:
            session.rollback()
            logger.error(f"批量写入失败: {e}", exc_info=True)
            raise
        finally:
            session.close()

        return inserted

    def query_latest(
        self, slave_addr: int = None, device_type: str = None,
        limit: int = 10,
    ) -> list:
        """查询最近的采集数据"""
        if not self._session_factory:
            raise RuntimeError("数据库未初始化")

        session = self._session_factory()
        try:
            query = session.query(PlcData)
            if slave_addr is not None:
                query = query.filter(PlcData.slave_addr == slave_addr)
            if device_type is not None:
                query = query.filter(PlcData.device_type == device_type)
            return (
                query
                .order_by(PlcData.timestamp.desc())
                .limit(limit)
                .all()
            )
        finally:
            session.close()

    def query_fault_events(self, limit: int = 200) -> List[dict]:
        """查询故障事件（从 fault_log 字段解析，按 collector_id 过滤）"""
        if not self._session_factory:
            return []

        session = self._session_factory()
        try:
            query = (
                session.query(PlcData.fault_log, PlcData.timestamp,
                              PlcData.slave_addr, PlcData.device_name)
                .filter(PlcData.fault_log.isnot(None))
                .filter(PlcData.fault_log != "")
            )
            if self._collector_id:
                query = query.filter(PlcData.collector_id == self._collector_id)
            rows = (
                query
                .order_by(PlcData.timestamp.desc())
                .limit(500)
                .all()
            )

            events = []
            active_starts = {}

            for row in reversed(list(rows)):
                try:
                    items = json.loads(row.fault_log)
                except (json.JSONDecodeError, TypeError):
                    continue
                for ev in items:
                    key = f"{ev.get('slave_addr')}:{ev.get('fault_name')}"
                    if ev.get("type") == "start":
                        active_starts[key] = ev.get("time", "")
                        events.append({
                            "device_name": ev.get("device_name", row.device_name or ""),
                            "slave_addr": ev.get("slave_addr", row.slave_addr),
                            "fault_name": ev.get("fault_name", ""),
                            "start_time": ev.get("time", ""),
                            "end_time": None,
                            "duration": None,
                        })
                    elif ev.get("type") == "end":
                        start_time_str = active_starts.pop(key, "")
                        for e in reversed(events):
                            if (e["slave_addr"] == ev.get("slave_addr")
                                    and e["fault_name"] == ev.get("fault_name")
                                    and e["end_time"] is None):
                                e["end_time"] = ev.get("time", "")
                                if start_time_str and e["end_time"]:
                                    try:
                                        from datetime import datetime as dt
                                        t0 = dt.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
                                        t1 = dt.strptime(e["end_time"], "%Y-%m-%d %H:%M:%S")
                                        delta = int((t1 - t0).total_seconds())
                                        mins, secs = divmod(delta, 60)
                                        hours, mins = divmod(mins, 60)
                                        if hours > 0:
                                            e["duration"] = f"{hours}h {mins}m {secs}s"
                                        elif mins > 0:
                                            e["duration"] = f"{mins}m {secs}s"
                                        else:
                                            e["duration"] = f"{secs}s"
                                    except ValueError:
                                        pass
                                break

            events.reverse()
            return events[:limit]
        finally:
            session.close()

    # ============================================================
    # 数据清理
    # ============================================================

    def cleanup_old_data(
        self, days: int = 30,
        device_keys: list = None,
        batch_size: int = 10000,
    ) -> int:
        """清理超过指定天数的历史采集数据"""
        if not self._session_factory:
            return 0

        cutoff = datetime.now() - timedelta(days=days)
        total_deleted = 0

        try:
            while True:
                session = self._session_factory()
                try:
                    query = (
                        session.query(PlcData.id)
                        .filter(PlcData.timestamp < cutoff)
                        .limit(batch_size)
                    )

                    ids = [row[0] for row in query.all()]
                    if not ids:
                        break

                    deleted = (
                        session.query(PlcData)
                        .filter(PlcData.id.in_(ids))
                        .delete(synchronize_session=False)
                    )
                    session.commit()
                    total_deleted += deleted

                except Exception as e:
                    session.rollback()
                    logger.warning(f"分批清理中断: {e}")
                    break
                finally:
                    session.close()

                import time
                time.sleep(0.1)

        except Exception as e:
            logger.warning(f"清理过期数据失败: {e}")

        if total_deleted > 0:
            logger.info(f"已清理 {total_deleted} 条过期数据（{days}天前）")

        return total_deleted

    # ============================================================
    # 设备类型定义查询
    # ============================================================

    def get_device_type_defs(self) -> List[dict]:
        """查询所有设备类型定义"""
        if not self._session_factory:
            return []

        session = self._session_factory()
        try:
            rows = session.query(DeviceTypeDef).all()
            result = []
            for row in rows:
                result.append({
                    "id": row.id,
                    "device_type": row.device_type,
                    "display_name": row.display_name,
                    "default_name_prefix": row.default_name_prefix,
                    "read_mode": row.read_mode,
                    "reg_base": row.reg_base,
                    "reg_count": row.reg_count,
                    "read_groups": row.read_groups,
                    "registers": row.registers,
                    "parse_rules": row.parse_rules,
                    "bit_fields": row.bit_fields,
                    "run_mode_rules": row.run_mode_rules,
                    "fault_names": row.fault_names,
                    "display_fields": row.display_fields,
                    "status_map": row.status_map,
                    "value_mappings": row.value_mappings,
                })
            return result
        finally:
            session.close()

    def upsert_device_type_def(self, type_def: dict):
        """插入或更新设备类型定义"""
        if not self._session_factory:
            raise RuntimeError("数据库未初始化")

        session = self._session_factory()
        try:
            existing = (
                session.query(DeviceTypeDef)
                .filter(DeviceTypeDef.device_type == type_def["device_type"])
                .first()
            )
            if existing:
                for key, value in type_def.items():
                    if key != "id":
                        setattr(existing, key, value)
            else:
                row = DeviceTypeDef(**type_def)
                session.add(row)

            session.commit()
            logger.info(f"设备类型定义已保存: {type_def['device_type']}")
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> dict:
        """获取数据库统计信息"""
        if not self._session_factory:
            return {}

        session = self._session_factory()
        try:
            total = session.query(PlcData).count()
            devices = session.query(PlcData.slave_addr).distinct().count()
            type_count = session.query(DeviceTypeDef).count()

            return {
                "total_records": total,
                "device_count": devices,
                "device_type_count": type_count,
                "engine": self._config.engine,
                "database": self._config.database,
            }
        finally:
            session.close()

    def close(self):
        """关闭数据库连接"""
        if self._engine:
            self._engine.dispose()
            logger.info("数据库连接已关闭")
