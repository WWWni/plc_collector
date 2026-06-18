"""
Modbus TCP 网关传输层 (模式B)
==============================
ZLAN5143D转化协议设为Modbus TCP，端口自动变为502。
PC程序使用pymodbus的AsyncModbusTcpClient连接502端口，
ZLAN5143D自动完成Modbus TCP到RTU的协议转换。

此模式下可利用ZLAN5143D的存储型Modbus网关特性，
网口端可在3ms内响应查询，大幅提升采集速度。
"""

import asyncio
import logging
from typing import List, Optional

from transport.base import TransportBase


logger = logging.getLogger("plc_collector.transport.modbus_tcp")


def _detect_slave_param_name() -> str:
    """通过内省pymodbus函数签名自动检测从站地址参数名

    不同版本参数名不同:
      - pymodbus 2.x:  unit
      - pymodbus 3.0~3.6: slave
      - pymodbus 3.7+: device_id
    """
    try:
        import inspect
        from pymodbus.client.mixin import ModbusClientMixin
        sig = inspect.signature(ModbusClientMixin.read_holding_registers)
        params = sig.parameters
        if "device_id" in params:
            return "device_id"
        if "slave" in params:
            return "slave"
        if "unit" in params:
            return "unit"
    except Exception:
        pass
    # 无法检测时默认用 slave (pymodbus 3.x 早期版本)
    return "slave"


_SLAVE_PARAM = _detect_slave_param_name()
logger.info(f"pymodbus从站地址参数名: {_SLAVE_PARAM}")


def _slave_kwargs(slave_addr: int) -> dict:
    """根据当前pymodbus版本返回正确的从站地址参数"""
    return {_SLAVE_PARAM: slave_addr}


class ModbusTcpTransport(TransportBase):
    """
    Modbus TCP网关模式传输层

    ZLAN5143D配置: 工作模式=TCP服务器, 转化协议=Modbus TCP, 端口=502
    PC端: 使用pymodbus连接ZLAN5143D的IP:502
    """

    def __init__(
        self,
        host: str,
        port: int = 502,
        tcp_timeout: float = 5.0,
        tcp_retry: int = 3,
        modbus_timeout: float = 1.0,
        modbus_retry: int = 0,
    ):
        self._host = host
        self._port = port
        self._tcp_timeout = tcp_timeout
        self._tcp_retry = tcp_retry
        self._modbus_timeout = modbus_timeout
        self._modbus_retry = modbus_retry
        self._client = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    async def connect(self) -> None:
        """建立Modbus TCP连接"""
        try:
            from pymodbus.client import AsyncModbusTcpClient

            self._client = AsyncModbusTcpClient(
                host=self._host,
                port=self._port,
                timeout=self._tcp_timeout,
                retries=self._tcp_retry,
            )
            connected = await self._client.connect()
            if connected:
                self._connected = True
                logger.info(
                    f"Modbus TCP连接成功: {self._host}:{self._port}"
                )
            else:
                self._connected = False
                raise ConnectionError(
                    f"Modbus TCP连接失败: {self._host}:{self._port}"
                )
        except ImportError:
            raise ImportError(
                "pymodbus库未安装，请运行: pip install pymodbus"
            )
        except Exception as e:
            self._connected = False
            logger.error(f"Modbus TCP连接失败: {e}")
            raise

    async def disconnect(self) -> None:
        """断开Modbus TCP连接"""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._connected = False
        logger.info("Modbus TCP连接已断开")

    async def _reconnect(self) -> None:
        """尝试重连"""
        await self.disconnect()
        await asyncio.sleep(0.5)
        await self.connect()

    async def read_registers(
        self,
        slave_addr: int,
        start_reg: int,
        quantity: int,
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
    ) -> List[int]:
        """
        读取保持寄存器 (功能码 0x03)

        pymodbus自动处理Modbus TCP帧头，
        ZLAN5143D自动将Modbus TCP转为RTU发送到串口。

        Args:
            timeout: 单次超时时间(秒)，None则使用全局默认值
            retry: 重试次数，None则使用全局默认值
        """
        if not self.is_connected:
            await self.connect()

        effective_timeout = timeout if timeout is not None else self._modbus_timeout
        effective_retry = retry if retry is not None else self._modbus_retry

        last_error = None
        total_attempts = effective_retry + 1
        for attempt in range(total_attempts):
            try:
                response = await asyncio.wait_for(
                    self._client.read_holding_registers(
                        address=start_reg,
                        count=quantity,
                        **_slave_kwargs(slave_addr),
                    ),
                    timeout=effective_timeout,
                )

                if response.isError():
                    raise RuntimeError(
                        f"Modbus读取失败: {response}"
                    )

                return list(response.registers)

            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"读取超时 ({effective_timeout}s)"
                )
                logger.warning(
                    f"读取失败 (第{attempt+1}/{total_attempts}次): {last_error}"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"读取失败 (第{attempt+1}/{total_attempts}次): {e}"
                )
            if attempt < effective_retry:
                try:
                    await self._reconnect()
                except Exception as re_err:
                    logger.error(f"重连失败: {re_err}")

        raise ConnectionError(
            f"读取寄存器失败，已重试{effective_retry}次: {last_error}"
        )

    async def write_register(
        self,
        slave_addr: int,
        reg_addr: int,
        value: int,
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
    ) -> bool:
        """写入单个寄存器 (功能码 0x06)"""
        if not self.is_connected:
            await self.connect()

        effective_timeout = timeout if timeout is not None else self._modbus_timeout
        effective_retry = retry if retry is not None else self._modbus_retry

        last_error = None
        total_attempts = effective_retry + 1
        for attempt in range(total_attempts):
            try:
                response = await asyncio.wait_for(
                    self._client.write_register(
                        address=reg_addr,
                        value=value,
                        **_slave_kwargs(slave_addr),
                    ),
                    timeout=effective_timeout,
                )
                if response.isError():
                    raise RuntimeError(f"Modbus写入失败: {response}")
                return True
            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"写入超时 ({effective_timeout}s)"
                )
                logger.warning(
                    f"写入失败 (第{attempt+1}/{total_attempts}次): {last_error}"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"写入失败 (第{attempt+1}/{total_attempts}次): {e}"
                )
            if attempt < effective_retry:
                try:
                    await self._reconnect()
                except Exception as re_err:
                    logger.error(f"重连失败: {re_err}")

        raise ConnectionError(
            f"写入寄存器失败，已重试{effective_retry}次: {last_error}"
        )

    async def write_registers(
        self,
        slave_addr: int,
        start_reg: int,
        values: List[int],
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
    ) -> bool:
        """写入多个寄存器 (功能码 0x10)"""
        if not self.is_connected:
            await self.connect()

        effective_timeout = timeout if timeout is not None else self._modbus_timeout
        effective_retry = retry if retry is not None else self._modbus_retry

        last_error = None
        total_attempts = effective_retry + 1
        for attempt in range(total_attempts):
            try:
                response = await asyncio.wait_for(
                    self._client.write_registers(
                        address=start_reg,
                        values=values,
                        **_slave_kwargs(slave_addr),
                    ),
                    timeout=effective_timeout,
                )
                if response.isError():
                    raise RuntimeError(f"Modbus批量写入失败: {response}")
                return True
            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"批量写入超时 ({effective_timeout}s)"
                )
                logger.warning(
                    f"批量写入失败 (第{attempt+1}/{total_attempts}次): {last_error}"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"批量写入失败 (第{attempt+1}/{total_attempts}次): {e}"
                )
            if attempt < effective_retry:
                try:
                    await self._reconnect()
                except Exception as re_err:
                    logger.error(f"重连失败: {re_err}")

        raise ConnectionError(
            f"批量写入寄存器失败，已重试{effective_retry}次: {last_error}"
        )
