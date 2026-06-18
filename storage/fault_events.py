"""
故障事件检测与持久化工具
==========================
对比前后两轮采集的故障状态，检测新增/恢复的故障，
生成事件记录并附加到 data_dict["fault_log"] (JSON字符串)，
供 batch_insert 写入数据库。
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

logger = logging.getLogger("plc_collector.fault_events")

# 全局故障状态跟踪（进程级单例）
_last_faults: Dict[int, Set[str]] = {}  # slave_addr -> set of fault names


def reset_state():
    """重置故障跟踪状态（程序重启时调用）"""
    global _last_faults
    _last_faults.clear()


def restore_state(active_faults_by_device: Dict[int, Set[str]]):
    """
    从数据库恢复故障跟踪状态

    Args:
        active_faults_by_device: slave_addr -> 当前活跃故障名集合
    """
    global _last_faults
    _last_faults = {k: set(v) for k, v in active_faults_by_device.items()}


def attach_fault_events(data_list: List[dict]) -> None:
    """
    检测故障变化并将事件附加到 data_dict["fault_log"]

    遍历本轮所有设备数据，对比 _last_faults 状态：
    - 新增故障: event_type="start"
    - 恢复故障: event_type="end"（含持续时长）
    无变化时 fault_log 保持 None，不写入数据库。

    Args:
        data_list: 本轮采集数据字典列表（会被原地修改）
    """
    for data in data_list:
        addr = data.get("slave_addr", 0)
        name = data.get("device_name", f"设备-{addr}")
        current_faults = set(data.get("active_faults", []))
        prev_faults = _last_faults.get(addr, set())

        events = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 新增故障
        for fault in sorted(current_faults - prev_faults):
            events.append({
                "type": "start",
                "device_name": name,
                "slave_addr": addr,
                "fault_name": fault,
                "time": now_str,
            })

        # 恢复的故障（需要回溯上次的开始时间来计算持续时长）
        for fault in sorted(prev_faults - current_faults):
            events.append({
                "type": "end",
                "device_name": name,
                "slave_addr": addr,
                "fault_name": fault,
                "time": now_str,
            })

        # 只有有变化时才写入 fault_log
        if events:
            data["fault_log"] = json.dumps(events, ensure_ascii=False)

        _last_faults[addr] = current_faults


def get_active_faults_state() -> Dict[int, Set[str]]:
    """获取当前各设备的活跃故障状态（用于持久化）"""
    return {k: set(v) for k, v in _last_faults.items()}
