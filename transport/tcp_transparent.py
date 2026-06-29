"""
TCP透传传输层 (模式A)
======================
ZLAN5143D作为TCP Server，转化协议设为NONE（透明传输）。
PC程序通过asyncio TCP Socket连接ZLAN5143D，自行构造Modbus RTU帧并通过TCP发送。

关键要点:
- TCP是流式协议，需正确分帧（根据请求推算响应长度）
- RS485半双工，使用asyncio.Lock保证一问一答
- 超时重试机制
"""

import asyncio
import logging
import socket
from typing import List, Optional

from transport.base import TransportBase
from protocol.modbus_rtu import (
    build_read_holding,
    build_read_input,
    build_write_single,
    build_write_multiple,
    parse_read_response,
    parse_write_response,
    get_expected_response_length,
    ModbusException,
)


logger = logging.getLogger("plc_collector.transport.tcp")


class TcpTransparentTransport(TransportBase):
    """
    TCP透传模式传输层

    ZLAN5143D配置: 工作模式=TCP服务器, 转化协议=NONE, 端口=4196
    PC端: 作为TCP Client连接到ZLAN5143D的IP:Port
    """

    def __init__(
        self,
        host: str,
        port: int,
        tcp_timeout: float = 1.0,
        modbus_timeout: float = 1.0,
        modbus_retry: int = 0,
        modbus_retry_delay: float = 0.1,
    ):
        self._host = host
        self._port = port
        self._tcp_timeout = tcp_timeout
        self._modbus_timeout = modbus_timeout
        self._modbus_retry = modbus_retry
        self._modbus_retry_delay = modbus_retry_delay

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()  # 半双工通信锁
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._writer is not None

    async def connect(self) -> None:
        """建立TCP连接到ZLAN5143D"""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._tcp_timeout,
            )
            # TCP Keep-Alive：检测死连接
            sock = self._writer.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, "TCP_KEEPIDLE"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                if hasattr(socket, "TCP_KEEPINTVL"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                if hasattr(socket, "TCP_KEEPCNT"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            self._connected = True
            logger.info(f"TCP连接成功: {self._host}:{self._port}")
        except Exception as e:
            self._connected = False
            logger.error(f"TCP连接失败: {self._host}:{self._port} - {e}")
            raise

    async def disconnect(self) -> None:
        """断开TCP连接"""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        self._connected = False
        logger.info("TCP连接已断开")

    async def _reconnect(self) -> None:
        """尝试重连"""
        await self.disconnect()
        await asyncio.sleep(0.5)
        await self.connect()

    async def _send_and_receive(
        self, request_frame: bytes, expected_len: int, timeout: float
    ) -> bytes:
        """
        发送请求帧并接收响应帧（内部方法，需在锁内调用）

        Args:
            request_frame: 完整的Modbus RTU请求帧
            expected_len: 预期响应帧长度
            timeout: 接收超时时间(秒)

        Returns:
            完整的响应帧
        """
        # 清空接收缓冲区（丢弃残留数据）
        try:
            while not self._reader.at_eof():
                self._reader.read_nowait()
        except Exception:
            pass

        # 发送请求
        self._writer.write(request_frame)
        await self._writer.drain()

        logger.debug(f"TX: {request_frame.hex()}")

        # 接收响应
        response = b""
        remaining = expected_len
        try:
            while remaining > 0:
                chunk = await asyncio.wait_for(
                    self._reader.read(remaining),
                    timeout=timeout,
                )
                if not chunk:
                    raise ConnectionError("TCP连接已断开（EOF）")
                response += chunk
                remaining -= len(chunk)

                # 检测Modbus异常响应
                # 异常帧: [地址(1)][功能码|0x80(1)][异常码(1)][CRC(2)] = 5字节
                # 正常响应更长，检测到异常时将期望长度调整为5，避免无效等待
                if len(response) >= 2 and remaining > 0 and (response[1] & 0x80):
                    remaining = 5 - len(response)
                    if remaining < 0:
                        remaining = 0
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"接收超时 ({timeout}s), "
                f"已收到{len(response)}/{expected_len}字节"
            )

        logger.debug(f"RX: {response.hex()}")
        return response

    async def _execute_request(
        self,
        request_frame: bytes,
        expected_len: int,
        slave_addr: int,
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
    ) -> bytes:
        """
        执行一次请求-响应（带重试），使用锁保证半双工

        Args:
            request_frame: 请求帧
            expected_len: 预期响应长度
            slave_addr: 从站地址
            timeout: 单次超时时间(秒)，None则使用全局默认值
            retry: 重试次数，None则使用全局默认值

        Returns:
            响应帧
        """
        effective_timeout = timeout if timeout is not None else self._modbus_timeout
        effective_retry = retry if retry is not None else self._modbus_retry

        async with self._lock:
            last_error = None
            total_attempts = effective_retry + 1

            for attempt in range(total_attempts):
                try:
                    if not self.is_connected:
                        await self.connect()

                    response = await self._send_and_receive(
                        request_frame, expected_len, effective_timeout
                    )

                    # 检测Modbus异常响应
                    # 异常帧: [地址(1)][功能码|0x80(1)][异常码(1)][CRC(2)] = 5字节
                    if len(response) >= 2 and (response[1] & 0x80):
                        exc_code = response[2] if len(response) >= 3 else 0
                        last_error = ModbusException(response[1] & 0x7F, exc_code)
                        logger.warning(
                            f"[从站{slave_addr}] Modbus异常响应 (第{attempt+1}/{total_attempts}次): {last_error}"
                        )
                        # Modbus应用层异常：TCP链路正常，不需要重连
                    else:
                        return response

                except (ConnectionError, TimeoutError, OSError) as e:
                    last_error = e
                    logger.warning(
                        f"[从站{slave_addr}] 通信失败 (第{attempt+1}/{total_attempts}次): {e}"
                    )
                    if attempt < effective_retry:
                        try:
                            await self._reconnect()
                        except Exception as re_err:
                            logger.error(f"[从站{slave_addr}] 重连失败: {re_err}")
                    continue  # 网络异常重连后直接进下一轮，不走通用延迟

                # 通用重试延迟：Modbus异常响应后等待总线恢复
                if attempt < effective_retry:
                    await asyncio.sleep(self._modbus_retry_delay)

            raise ConnectionError(
                f"[从站{slave_addr}] 通信失败，已重试{effective_retry}次: {last_error}"
            )

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
        """读取寄存器 (0x03 保持 / 0x04 输入)"""
        if read_function == "input":
            request = build_read_input(slave_addr, start_reg, quantity)
        else:
            request = build_read_holding(slave_addr, start_reg, quantity)
        expected_len = get_expected_response_length(request)

        if expected_len is None:
            raise ValueError("无法推算预期响应长度")

        response = await self._execute_request(
            request, expected_len, slave_addr,
            timeout=timeout, retry=retry,
        )
        return parse_read_response(response, slave_addr)

    async def write_register(
        self,
        slave_addr: int,
        reg_addr: int,
        value: int,
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
    ) -> bool:
        """写入单个寄存器 (0x06)"""
        request = build_write_single(slave_addr, reg_addr, value)
        expected_len = get_expected_response_length(request)

        response = await self._execute_request(
            request, expected_len, slave_addr,
            timeout=timeout, retry=retry,
        )
        parse_write_response(response, slave_addr)
        return True

    async def write_registers(
        self,
        slave_addr: int,
        start_reg: int,
        values: List[int],
        *,
        timeout: Optional[float] = None,
        retry: Optional[int] = None,
    ) -> bool:
        """写入多个寄存器 (0x10)"""
        request = build_write_multiple(slave_addr, start_reg, values)
        expected_len = get_expected_response_length(request)

        response = await self._execute_request(
            request, expected_len, slave_addr,
            timeout=timeout, retry=retry,
        )
        parse_write_response(response, slave_addr)
        return True
