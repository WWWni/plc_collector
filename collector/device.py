"""
单台设备采集逻辑
=================
封装一台设备的完整采集流程，支持多设备类型:
1. 根据 device_type 查找对应的协议定义
2. 按协议定义的寄存器地址读取数据 (支持连续读取和分组读取)
3. 调用设备类型的解析函数将原始值转换为结构化数据
4. 异常处理和日志记录
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from transport.base import TransportBase
from protocol.device_types import get_safe, get_default_type


logger = logging.getLogger("plc_collector.collector.device")


class Device:
    """
    单台设备封装

    每台设备对应一个从站地址，通过共享的TransportBase实例进行通信。
    通过 device_type 参数选择对应的协议解析模块。
    支持可选的 per-device timeout/retry 配置，优先级高于传输层全局默认值。
    """

    def __init__(
        self,
        slave_addr: int,
        name: str,
        transport: TransportBase,
        *,
        device_type: str = "",
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
        server_index: int = 0,
        server_name: str = "",
    ):
        self.slave_addr = slave_addr
        self.name = name or f"设备-{slave_addr}"
        self.device_type = device_type
        self._transport = transport
        self._type_def = get_safe(device_type)  # 设备类型协议模块
        self._timeout = timeout      # None = 使用传输层全局默认
        self._retry = retry          # None = 使用传输层全局默认
        self.server_index = server_index
        self.server_name = server_name
        self._last_data: Optional[Dict[str, Any]] = None
        self._last_error: Optional[str] = None
        self._success_count = 0
        self._error_count = 0

    @property
    def last_data(self) -> Optional[Dict[str, Any]]:
        """最近一次采集数据"""
        return self._last_data

    @property
    def stats(self) -> dict:
        """采集统计"""
        total = self._success_count + self._error_count
        return {
            "device": self.name,
            "slave_addr": self.slave_addr,
            "device_type": self.device_type,
            "success": self._success_count,
            "error": self._error_count,
            "total": total,
            "error_rate": (
                f"{self._error_count / total * 100:.1f}%"
                if total > 0 else "N/A"
            ),
        }

    async def collect(self) -> Optional[Dict[str, Any]]:
        """
        执行一次数据采集

        根据设备类型的寄存器定义读取并解析数据:
        - 连续读取 (REG_BASE + REG_COUNT): 如圆机面板
        - 分组读取 (READ_GROUPS): 如N90SC-4计米器

        Returns:
            解析后的数据字典，采集失败返回None
        """
        try:
            type_def = self._type_def

            if hasattr(type_def, 'READ_GROUPS'):
                # 分组读取 (非连续寄存器地址)
                all_values = {}
                for i, group in enumerate(type_def.READ_GROUPS):
                    values = await self._transport.read_registers(
                        slave_addr=self.slave_addr,
                        start_reg=group["start"],
                        quantity=group["count"],
                        timeout=self._timeout,
                        retry=self._retry,
                        read_function=getattr(type_def, 'READ_FUNCTION', 'holding'),
                    )
                    all_values[f"group_{i}"] = values
                data = type_def.parse_registers(all_values)
            else:
                # 连续读取 (标准方式)
                values = await self._transport.read_registers(
                    slave_addr=self.slave_addr,
                    start_reg=type_def.REG_BASE,
                    quantity=type_def.REG_COUNT,
                    timeout=self._timeout,
                    retry=self._retry,
                    read_function=getattr(type_def, 'READ_FUNCTION', 'holding'),
                )
                data = type_def.parse_registers(values)

            # 添加元数据
            data["timestamp"] = datetime.now()
            data["slave_addr"] = self.slave_addr
            data["device_name"] = self.name
            data["device_type"] = self.device_type
            data["server_index"] = self.server_index
            data["server_name"] = self.server_name
            data["run_mode"] = type_def.get_run_mode(data)
            data["active_faults"] = type_def.get_active_faults(data)

            self._last_data = data
            self._last_error = None
            self._success_count += 1

            logger.debug(
                f"[{self.name}] 采集成功: "
                f"类型={self.device_type}, "
                f"模式={data['run_mode']}"
            )

            return data

        except Exception as e:
            self._error_count += 1
            self._last_error = str(e)
            logger.warning(f"[{self.name}] 采集失败: {e}")
            return None

    def __repr__(self):
        return (
            f"Device(name={self.name!r}, addr={self.slave_addr}, "
            f"type={self.device_type})"
        )
