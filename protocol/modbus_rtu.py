"""
Modbus RTU 协议帧构造与解析模块
================================
用于TCP透传模式下，手动构造Modbus RTU帧并通过TCP Socket发送。
支持功能码: 0x03(读保持寄存器), 0x06(写单个寄存器), 0x10(写多个寄存器)

帧格式:
  请求: [从站地址(1B)] [功能码(1B)] [数据(NB)] [CRC16(2B)]
  响应: [从站地址(1B)] [功能码(1B)] [数据(NB)] [CRC16(2B)]
  异常: [从站地址(1B)] [功能码+0x80(1B)] [异常码(1B)] [CRC16(2B)]
"""

import struct
from typing import List, Tuple, Optional


# ============================================================
# CRC16 校验 (标准Modbus CRC16, 多项式 0xA001)
# ============================================================

# 预计算的CRC16查找表，加速计算
_CRC16_TABLE = [0] * 256

def _init_crc16_table():
    """初始化CRC16查找表"""
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        _CRC16_TABLE[i] = crc

_init_crc16_table()


def calc_crc16(data: bytes) -> int:
    """
    计算Modbus CRC16校验值

    Args:
        data: 待校验的数据字节串

    Returns:
        CRC16校验值 (16位无符号整数)

    Example:
        >>> calc_crc16(bytes([0x01, 0x03, 0x00, 0x0D, 0x00, 0x02]))
        # 返回CRC16值
    """
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC16_TABLE[(crc ^ byte) & 0xFF]
    return crc


def append_crc16(data: bytes) -> bytes:
    """
    计算CRC16并追加到数据末尾（低字节在前，高字节在后）

    Args:
        data: 原始数据（不含CRC）

    Returns:
        追加CRC后的完整帧
    """
    crc = calc_crc16(data)
    # Modbus RTU: CRC低字节在前
    return data + struct.pack("<H", crc)


def verify_crc16(frame: bytes) -> bool:
    """
    校验完整帧的CRC是否正确

    Args:
        frame: 完整帧数据（含CRC）

    Returns:
        True=校验通过, False=校验失败
    """
    if len(frame) < 4:
        return False
    payload = frame[:-2]
    expected_crc = struct.unpack("<H", frame[-2:])[0]
    return calc_crc16(payload) == expected_crc


# ============================================================
# 请求帧构造
# ============================================================

def build_read_holding(slave_addr: int, start_reg: int, quantity: int) -> bytes:
    """
    构造读保持寄存器请求帧 (功能码 0x03)

    Args:
        slave_addr: 从站地址 (1-128)
        start_reg: 起始寄存器地址 (0-65535)
        quantity: 读取寄存器数量 (1-125)

    Returns:
        完整的Modbus RTU请求帧（含CRC）

    Example:
        # 读从站1的寄存器0x000D开始2个寄存器
        >>> frame = build_read_holding(0x01, 0x000D, 2)
        >>> frame.hex()
        '0103000d0002...'
    """
    if not 1 <= slave_addr <= 247:
        raise ValueError(f"从站地址超出范围(1-247): {slave_addr}")
    if not 1 <= quantity <= 125:
        raise ValueError(f"寄存器数量超出范围(1-125): {quantity}")

    pdu = struct.pack(">BBH H", slave_addr, 0x03, start_reg, quantity)
    return append_crc16(pdu)


def build_write_single(slave_addr: int, reg_addr: int, value: int) -> bytes:
    """
    构造写单个寄存器请求帧 (功能码 0x06)

    Args:
        slave_addr: 从站地址 (1-247)
        reg_addr: 寄存器地址 (0-65535)
        value: 写入值 (0-65535)

    Returns:
        完整的Modbus RTU请求帧（含CRC）
    """
    if not 1 <= slave_addr <= 247:
        raise ValueError(f"从站地址超出范围(1-247): {slave_addr}")
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"写入值超出范围(0-65535): {value}")

    pdu = struct.pack(">BBH H", slave_addr, 0x06, reg_addr, value)
    return append_crc16(pdu)


def build_write_multiple(slave_addr: int, start_reg: int, values: List[int]) -> bytes:
    """
    构造写多个寄存器请求帧 (功能码 0x10)

    Args:
        slave_addr: 从站地址 (1-247)
        start_reg: 起始寄存器地址 (0-65535)
        values: 要写入的寄存器值列表，每个值0-65535

    Returns:
        完整的Modbus RTU请求帧（含CRC）
    """
    if not 1 <= slave_addr <= 247:
        raise ValueError(f"从站地址超出范围(1-247): {slave_addr}")
    quantity = len(values)
    if not 1 <= quantity <= 123:
        raise ValueError(f"寄存器数量超出范围(1-123): {quantity}")

    byte_count = quantity * 2
    pdu = struct.pack(">BBH HB", slave_addr, 0x10, start_reg, quantity, byte_count)
    for v in values:
        if not 0 <= v <= 0xFFFF:
            raise ValueError(f"写入值超出范围(0-65535): {v}")
        pdu += struct.pack(">H", v)
    return append_crc16(pdu)


# ============================================================
# 响应帧解析
# ============================================================

class ModbusException(Exception):
    """Modbus异常响应"""
    EXCEPTION_CODES = {
        0x01: "非法功能码",
        0x02: "非法数据地址",
        0x03: "非法数据值",
        0x04: "从站设备故障",
        0x05: "确认(请求已接受，正在处理)",
        0x06: "从站设备忙",
        0x08: "存储奇偶校验错误",
        0x0A: "网关路径不可用",
        0x0B: "网关目标设备无响应",
    }

    def __init__(self, function_code: int, exception_code: int):
        self.function_code = function_code
        self.exception_code = exception_code
        desc = self.EXCEPTION_CODES.get(exception_code, "未知异常")
        super().__init__(f"Modbus异常 [功能码=0x{function_code:02X}, 异常码=0x{exception_code:02X}]: {desc}")


def _check_frame(frame: bytes, expected_slave: int) -> Tuple[int, bytes]:
    """
    校验帧的完整性：长度、CRC、从站地址、是否异常响应

    Returns:
        (function_code, payload_data) — payload_data 不含从站地址和功能码

    Raises:
        ValueError: 帧格式错误
        ModbusException: 从站返回异常响应
    """
    if len(frame) < 4:
        raise ValueError(f"帧长度不足: {len(frame)} 字节")

    if not verify_crc16(frame):
        raise ValueError(f"CRC校验失败: {frame.hex()}")

    slave_addr = frame[0]
    func_code = frame[1]

    # 检查异常响应（功能码最高位为1）
    if func_code & 0x80:
        exc_code = frame[2] if len(frame) >= 5 else 0
        raise ModbusException(func_code & 0x7F, exc_code)

    if slave_addr != expected_slave:
        raise ValueError(
            f"从站地址不匹配: 期望={expected_slave}, 实际={slave_addr}"
        )

    # 返回功能码和有效载荷（不含从站地址、功能码、CRC）
    payload = frame[2:-2]
    return func_code, payload


def parse_read_response(frame: bytes, expected_slave: int) -> List[int]:
    """
    解析读保持寄存器响应帧 (功能码 0x03)

    Args:
        frame: 完整响应帧（含CRC）
        expected_slave: 期望的从站地址

    Returns:
        寄存器值列表（每个值16位无符号整数）

    Example:
        # 响应: 01 03 04 01 00 00 AA CRC CRC
        >>> values = parse_read_response(frame, 0x01)
        >>> values
        [256, 170]
    """
    func_code, payload = _check_frame(frame, expected_slave)

    if func_code != 0x03:
        raise ValueError(f"期望功能码0x03，实际0x{func_code:02X}")

    if len(payload) < 1:
        raise ValueError("响应数据不完整")

    byte_count = payload[0]
    data = payload[1:]

    if len(data) != byte_count:
        raise ValueError(
            f"字节数不匹配: 声明={byte_count}, 实际={len(data)}"
        )

    if byte_count % 2 != 0:
        raise ValueError(f"字节数不是2的整数倍: {byte_count}")

    # 解析寄存器值（每个寄存器2字节，大端序）
    values = []
    for i in range(0, byte_count, 2):
        val = struct.unpack(">H", data[i:i+2])[0]
        values.append(val)

    return values


def parse_write_response(frame: bytes, expected_slave: int) -> Tuple[int, int]:
    """
    解析写寄存器响应帧 (功能码 0x06 或 0x10)

    Args:
        frame: 完整响应帧（含CRC）
        expected_slave: 期望的从站地址

    Returns:
        (reg_addr, value_or_quantity)
        - 0x06: (寄存器地址, 写入值)
        - 0x10: (起始地址, 寄存器数量)
    """
    func_code, payload = _check_frame(frame, expected_slave)

    if func_code not in (0x06, 0x10):
        raise ValueError(f"期望功能码0x06或0x10，实际0x{func_code:02X}")

    if len(payload) < 4:
        raise ValueError("写响应数据不完整")

    reg_addr = struct.unpack(">H", payload[0:2])[0]
    value = struct.unpack(">H", payload[2:4])[0]

    return reg_addr, value


def get_expected_response_length(request_frame: bytes) -> Optional[int]:
    """
    根据请求帧推算响应帧的预期长度（用于TCP接收时的帧边界判断）

    Args:
        request_frame: 发送的请求帧

    Returns:
        预期响应帧长度，无法确定时返回None
    """
    if len(request_frame) < 8:
        return None

    func_code = request_frame[1]

    if func_code == 0x03:
        # 读保持寄存器：响应长度 = 1(地址) + 1(功能码) + 1(字节数) + N(数据) + 2(CRC)
        quantity = struct.unpack(">H", request_frame[4:6])[0]
        return 3 + quantity * 2 + 2

    elif func_code == 0x06:
        # 写单个寄存器：响应帧长度固定为8字节
        return 8

    elif func_code == 0x10:
        # 写多个寄存器：响应帧长度固定为8字节
        return 8

    return None
