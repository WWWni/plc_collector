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
        """初始化数据库引擎、建表（plc_data 按天分区）"""
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

        # device_type_def 用 ORM 建表（无分区需求）
        from storage.models import DeviceTypeDef, DeviceRegistry
        DeviceTypeDef.__table__.create(self._engine, checkfirst=True)

        # device_registry 设备注册表
        DeviceRegistry.__table__.create(self._engine, checkfirst=True)

        # plc_data 用原生 DDL 建分区表
        self._create_partitioned_table()

        # 创建分区锁表，尝试获取今天的分区锁
        self._create_partition_lock_table()
        if self._acquire_partition_lock():
            # 今天第一个启动的实例，负责创建未来 7 天的分区
            self._ensure_future_partitions(days_ahead=7)
        else:
            logger.info("今日分区已由其他实例创建，跳过")

        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False
        )

        logger.info(
            f"数据库初始化成功: {self._config.engine}://"
            f"{self._config.host}:{self._config.port}/{self._config.database}"
        )

    def _create_partitioned_table(self):
        """用原生 DDL 创建按天分区的 plc_data 表"""
        ddl = """
        CREATE TABLE IF NOT EXISTS plc_data (
            id BIGINT AUTO_INCREMENT,
            timestamp DATETIME NOT NULL,
            collector_id VARCHAR(50) NOT NULL DEFAULT '',
            server_index SMALLINT NOT NULL DEFAULT 0,
            slave_addr SMALLINT NOT NULL,
            device_name VARCHAR(50),
            device_type VARCHAR(50) NOT NULL,
            field_data JSON,
            run_mode VARCHAR(20),
            fault_log TEXT,
            PRIMARY KEY (id, timestamp),
            INDEX ix_plc_collector_time (collector_id, timestamp),
            INDEX ix_plc_server_device_time (server_index, slave_addr, timestamp)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        PARTITION BY RANGE (TO_DAYS(timestamp)) (
            PARTITION p_future VALUES LESS THAN MAXVALUE
        )
        """
        with self._engine.connect() as conn:
            conn.execute(text(ddl))
            conn.commit()

    def _ensure_future_partitions(self, days_ahead: int = 7):
        """创建未来 N 天的日分区（幂等操作，已存在的分区忽略）"""
        today = datetime.now().date()
        with self._engine.connect() as conn:
            for i in range(days_ahead + 1):
                day = today + timedelta(days=i)
                next_day = day + timedelta(days=1)
                part_name = f"p{day.strftime('%Y%m%d')}"
                alter_sql = (
                    f"ALTER TABLE plc_data REORGANIZE PARTITION p_future INTO ("
                    f"  PARTITION {part_name} VALUES LESS THAN (TO_DAYS('{next_day}')),"
                    f"  PARTITION p_future VALUES LESS THAN MAXVALUE"
                    f")"
                )
                try:
                    conn.execute(text(alter_sql))
                    conn.commit()
                except Exception:
                    # 分区已存在，忽略
                    conn.rollback()

    def _create_partition_lock_table(self):
        """创建分区锁表（轻量协调表，避免多 IPC 同时 ALTER TABLE 抢锁）"""
        ddl = """
        CREATE TABLE IF NOT EXISTS partition_lock (
            lock_date DATE PRIMARY KEY
        ) ENGINE=InnoDB
        """
        with self._engine.connect() as conn:
            conn.execute(text(ddl))
            conn.commit()

    def _acquire_partition_lock(self) -> bool:
        """尝试获取今天的分区锁，成功返回 True（今天第一个启动的实例）"""
        sql = text(
            "INSERT IGNORE INTO partition_lock (lock_date) VALUES (CURDATE())"
        )
        with self._engine.connect() as conn:
            result = conn.execute(sql)
            conn.commit()
            return result.rowcount > 0

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

        # 注册/更新设备（独立事务，不影响主写入）
        self._register_devices(data_list)

        return inserted

    def _register_devices(self, data_list: List[dict]):
        """注册设备到 device_registry（INSERT ON DUPLICATE KEY UPDATE）"""
        if not self._engine:
            return

        now = datetime.now()
        seen = set()
        for data in data_list:
            addr = data.get("slave_addr", 0)
            if addr in seen:
                continue
            seen.add(addr)

            sql = text("""
                INSERT INTO device_registry 
                    (device_name, device_type, slave_addr, collector_id, server_index, first_seen, last_seen)
                VALUES 
                    (:name, :type, :addr, :cid, :sidx, :now, :now)
                ON DUPLICATE KEY UPDATE 
                    device_name = VALUES(device_name),
                    device_type = VALUES(device_type),
                    last_seen = VALUES(last_seen)
            """)
            try:
                with self._engine.connect() as conn:
                    conn.execute(sql, {
                        "name": data.get("device_name", ""),
                        "type": data.get("device_type", "unknown"),
                        "addr": addr,
                        "cid": self._collector_id,
                        "sidx": data.get("server_index", 0),
                        "now": now,
                    })
                    conn.commit()
            except Exception:
                pass  # 注册失败不影响采集

    def query_device_registry(self) -> List[dict]:
        """查询所有已注册设备"""
        if not self._session_factory:
            return []

        from storage.models import DeviceRegistry
        session = self._session_factory()
        try:
            rows = (
                session.query(DeviceRegistry)
                .order_by(DeviceRegistry.collector_id, DeviceRegistry.slave_addr)
                .all()
            )
            return [
                {
                    "device_name": r.device_name,
                    "device_type": r.device_type,
                    "slave_addr": r.slave_addr,
                    "collector_id": r.collector_id,
                    "server_index": r.server_index,
                    "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                    "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                }
                for r in rows
            ]
        finally:
            session.close()

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
        """查询故障事件（从 fault_log 字段解析，按 collector_id 过滤，最近24小时）
        
        使用双层子查询优化：先在索引上过滤 id，再取 fault_log，避免全表扫描 TEXT 列。
        双层嵌套是 MySQL 对 LIMIT in IN-subquery 的 workaround。
        """
        if not self._session_factory:
            return []

        logger.info(f"[query_fault_events] collector_id={self._collector_id!r}")

        session = self._session_factory()
        try:
            since = datetime.now() - timedelta(hours=24)

            # 内层子查询：利用索引快速筛选 id（含 LIMIT）
            inner_q = (
                session.query(PlcData.id)
                .filter(PlcData.fault_log.isnot(None))
                .filter(PlcData.fault_log != "")
                .filter(PlcData.timestamp >= since)
            )
            if self._collector_id:
                inner_q = inner_q.filter(PlcData.collector_id == self._collector_id)
            inner_q = inner_q.order_by(PlcData.timestamp.desc()).limit(500)

            # 外层包装：绕过 MySQL "LIMIT in IN-subquery" 限制
            wrapper = inner_q.subquery().alias("id_wrapper")

            # 主查询：只取匹配行的完整数据
            rows = (
                session.query(PlcData.fault_log, PlcData.timestamp,
                              PlcData.slave_addr, PlcData.device_name)
                .filter(PlcData.id.in_(session.query(wrapper.c.id)))
                .order_by(PlcData.timestamp.desc())
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

    def cleanup_old_data(self, days: int = 30) -> int:
        """清理超过指定天数的历史数据（通过 DROP PARTITION 瞬间完成）"""
        if not self._engine:
            return 0

        cutoff_date = (datetime.now() - timedelta(days=days)).date()
        dropped = 0

        try:
            # 查询所有分区名和上界
            with self._engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT PARTITION_NAME, PARTITION_DESCRIPTION "
                    "FROM INFORMATION_SCHEMA.PARTITIONS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'plc_data' "
                    "ORDER BY PARTITION_ORDINAL_POSITION"
                ))
                partitions = result.fetchall()

            for part_name, part_desc in partitions:
                # 跳过兜底分区
                if part_name == "p_future":
                    continue
                # 分区名格式 pYYYYMMDD，提取日期
                if part_name.startswith("p") and len(part_name) == 9:
                    try:
                        part_date = datetime.strptime(part_name[1:], "%Y%m%d").date()
                        if part_date < cutoff_date:
                            with self._engine.connect() as conn:
                                conn.execute(text(
                                    f"ALTER TABLE plc_data DROP PARTITION {part_name}"
                                ))
                                conn.commit()
                            dropped += 1
                    except ValueError:
                        pass  # 非标准分区名，跳过
                    except Exception:
                        pass  # 分区可能已被其他 IPC 删除

        except Exception as e:
            logger.warning(f"清理过期分区失败: {e}")

        if dropped > 0:
            logger.info(f"已删除 {dropped} 个过期分区（{days}天前）")

        # 顺便确保未来分区存在
        self._ensure_future_partitions(days_ahead=7)

        return dropped

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
