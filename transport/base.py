"""
传输层抽象基类
==============
定义TCP透传和Modbus TCP两种传输模式的统一接口。
"""

from abc import ABC, abstractmethod
from typing import List, Optional


class TransportBase(ABC):
    """传输层抽象基类，所有传输模式必须实现以下接口"""

    @abstractmethod
    async def connect(self) -> None:
        """建立与ZLAN5143D的连接"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        ...

    @abstractmethod
    async def read_registers(
        self,
        slave_addr: int,
        start_reg: int,
        quantity: int,
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
        read_function: str = "holding",
    ) -> List[int]:
        """
        读取寄存器

        Args:
            slave_addr: 从站地址 (1-128)
            start_reg: 起始寄存器地址
            quantity: 读取数量
            timeout: 单次超时时间(秒)，None则使用全局默认值
            retry: 重试次数，None则使用全局默认值
            read_function: 读取功能类型，"holding"=读保持寄存器(0x03)，
                           "input"=读输入寄存器(0x04)

        Returns:
            寄存器值列表
        """
        ...

    @abstractmethod
    async def write_register(
        self,
        slave_addr: int,
        reg_addr: int,
        value: int,
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
    ) -> bool:
        """
        写入单个寄存器

        Args:
            slave_addr: 从站地址
            reg_addr: 寄存器地址
            value: 写入值
            timeout: 单次超时时间(秒)，None则使用全局默认值
            retry: 重试次数，None则使用全局默认值

        Returns:
            是否写入成功
        """
        ...

    @abstractmethod
    async def write_registers(
        self,
        slave_addr: int,
        start_reg: int,
        values: List[int],
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
    ) -> bool:
        """
        写入多个寄存器

        Args:
            slave_addr: 从站地址
            start_reg: 起始寄存器地址
            values: 寄存器值列表
            timeout: 单次超时时间(秒)，None则使用全局默认值
            retry: 重试次数，None则使用全局默认值

        Returns:
            是否写入成功
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """当前连接状态"""
        ...
