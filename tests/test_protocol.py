"""
单元测试 — Modbus RTU协议层 & 寄存器解析
==========================================
运行: python -m pytest tests/test_protocol.py -v
或者: python tests/test_protocol.py
"""

import sys
import os
import struct

# 添加项目根目录到path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol.modbus_rtu import (
    calc_crc16,
    append_crc16,
    verify_crc16,
    build_read_holding,
    build_write_single,
    build_write_multiple,
    parse_read_response,
    parse_write_response,
    ModbusException,
    get_expected_response_length,
)
from protocol.generic_parser import GenericParser

# 圆机面板测试定义（原 seed_data.py 已删除，测试用内联定义）
WEAVING_PANEL_DEF = {
    "device_type": "weaving_panel",
    "display_name": "圆机面板",
    "default_name_prefix": "圆机",
    "read_mode": "contiguous",
    "reg_base": 2202,
    "reg_count": 20,
    "read_groups": None,
    "registers": [
        {"idx": i, "name": f"reg_{i}", "addr": 2202 + i, "desc": f"寄存器{i}"}
        for i in range(20)
    ],
    "parse_rules": [
        {"field": "current_gear_run", "op": "byte_split", "src_idx": 0, "byte": "high"},
        {"field": "current_gear_jog", "op": "byte_split", "src_idx": 0, "byte": "low"},
        {"field": "fabric_count",     "op": "combine32",  "src_indices": [1, 2]},
        {"field": "clean_count",      "op": "direct",     "src_idx": 3},
        {"field": "shift",            "op": "direct",     "src_idx": 4},
        {"field": "shift_a",          "op": "combine32",  "src_indices": [5, 6]},
        {"field": "shift_b",          "op": "combine32",  "src_indices": [7, 8]},
        {"field": "shift_c",          "op": "combine32",  "src_indices": [9, 10]},
        {"field": "oil_mode",         "op": "direct",     "src_idx": 11},
        {"field": "fabric_total",     "op": "combine32",  "src_indices": [12, 13]},
        {"field": "speed",            "op": "scale",      "src_idx": 16, "factor": 0.1},
        {"field": "yarn_len_1",       "op": "scale",      "src_idx": 17, "factor": 0.1},
        {"field": "yarn_len_2",       "op": "scale",      "src_idx": 18, "factor": 0.1},
        {"field": "yarn_len_3",       "op": "scale",      "src_idx": 19, "factor": 0.1},
    ],
    "bit_fields": [
        {"src_idx": 14, "byte": "high", "prefix": "rs_", "bits": {
            "2": {"name": "motor", "label": "马达"},
            "5": {"name": "fan", "label": "风扇"},
        }},
        {"src_idx": 14, "byte": "low", "prefix": "rs_", "bits": {
            "0": {"name": "jogging", "label": "点动"},
            "1": {"name": "stopped", "label": "停止"},
            "2": {"name": "running", "label": "运行"},
        }},
        {"src_idx": 15, "byte": "high", "prefix": "ft_", "bits": {
            "0": {"name": "fuse", "label": "保险丝"},
            "5": {"name": "overspeed", "label": "超速"},
            "7": {"name": "fabric_complete", "label": "织布完成"},
        }},
        {"src_idx": 15, "byte": "low", "prefix": "ft_", "bits": {
            "0": {"name": "yarn_break_upper", "label": "上断纱"},
            "5": {"name": "no_air", "label": "缺气"},
            "7": {"name": "safety_door", "label": "安全门"},
        }},
    ],
    "run_mode_rules": [
        {"field": "rs_running", "mode": "running"},
        {"field": "rs_jogging", "mode": "jogging"},
        {"field": "rs_stopped", "mode": "stopped"},
    ],
    "fault_names": [
        {"key": "ft_overspeed", "label": "超速"},
        {"key": "ft_fuse", "label": "保险丝"},
        {"key": "ft_no_air", "label": "缺气"},
        {"key": "ft_yarn_break_upper", "label": "上断纱"},
        {"key": "ft_safety_door", "label": "安全门"},
        {"key": "ft_fabric_complete", "label": "织布完成"},
    ],
    "display_fields": [
        {"key": "speed", "label": "转速", "unit": "rpm", "format": ".1f"},
    ],
    "chart_fields": [],
    "status_map": {},
    "value_mappings": {},
}
_wp_parser = GenericParser(WEAVING_PANEL_DEF)
REG_BASE = _wp_parser.REG_BASE
REG_COUNT = _wp_parser.REG_COUNT
parse_registers = _wp_parser.parse_registers
get_active_faults = _wp_parser.get_active_faults
get_run_mode = _wp_parser.get_run_mode


# ============================================================
# CRC16 测试
# ============================================================

def test_crc16_known_values():
    """测试CRC16计算 — 使用Modbus标准多项式0xA001交叉验证"""
    # 使用标准逐位计算作为参考实现进行交叉验证
    def _crc16_reference(data: bytes) -> int:
        """参考实现: 逐位计算Modbus CRC16"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    # 多个测试数据交叉验证
    test_data_list = [
        bytes([0x01, 0x03, 0x00, 0x0D, 0x00, 0x02]),
        bytes([0x01, 0x06, 0x10, 0x00, 0x00, 0x02]),
        bytes([0x01, 0x10, 0x00, 0x0D, 0x00, 0x02, 0x04, 0x01, 0x00, 0x00, 0xAA]),
        bytes([0x01, 0x03, 0x08, 0x9A, 0x00, 0x14]),
    ]

    for data in test_data_list:
        crc_fast = calc_crc16(data)
        crc_ref = _crc16_reference(data)
        assert crc_fast == crc_ref, (
            f"CRC不匹配: 查表法=0x{crc_fast:04X}, "
            f"参考法=0x{crc_ref:04X}, data={data.hex()}"
        )
        print(f"  CRC16({data.hex()}) = 0x{crc_fast:04X}")

    print("  PASS: CRC16标准测试向量")


def test_crc16_append_verify():
    """测试CRC追加和校验"""
    data = bytes([0x01, 0x03, 0x00, 0x0D, 0x00, 0x02])
    frame = append_crc16(data)

    # 帧长度 = 原始数据 + 2字节CRC
    assert len(frame) == len(data) + 2

    # CRC应该是低字节在前
    crc_low = frame[-2]
    crc_high = frame[-1]
    expected_crc = calc_crc16(data)
    assert crc_low == (expected_crc & 0xFF)
    assert crc_high == ((expected_crc >> 8) & 0xFF)

    # 校验应该通过
    assert verify_crc16(frame) == True
    print("  PASS: CRC追加和校验")


def test_crc16_verify_corrupt():
    """测试损坏帧的CRC校验"""
    data = bytes([0x01, 0x03, 0x00, 0x0D, 0x00, 0x02])
    frame = append_crc16(data)

    # 修改一个字节
    corrupted = bytearray(frame)
    corrupted[3] = 0xFF
    assert verify_crc16(bytes(corrupted)) == False
    print("  PASS: 损坏帧CRC校验")


# ============================================================
# 帧构造测试
# ============================================================

def test_build_read_holding():
    """测试读保持寄存器帧构造"""
    # 协议文档4.1示例: 读从站1的寄存器0x000D开始2个
    frame = build_read_holding(0x01, 0x000D, 2)

    assert frame[0] == 0x01  # 从站地址
    assert frame[1] == 0x03  # 功能码
    assert frame[2] == 0x00  # 起始地址高字节
    assert frame[3] == 0x0D  # 起始地址低字节
    assert frame[4] == 0x00  # 寄存器数量高字节
    assert frame[5] == 0x02  # 寄存器数量低字节
    assert verify_crc16(frame) == True

    print(f"  读请求帧: {frame.hex()}")
    print("  PASS: 读保持寄存器帧构造")


def test_build_read_holding_panel_regs():
    """测试读取面板寄存器(2202-2221)的帧构造"""
    # 2202 = 0x089A, 20个寄存器 = 0x14
    frame = build_read_holding(0x01, 0x089A, 20)

    assert frame[0] == 0x01
    assert frame[1] == 0x03
    assert struct.unpack(">H", frame[2:4])[0] == 0x089A  # 2202
    assert struct.unpack(">H", frame[4:6])[0] == 0x0014  # 20
    assert verify_crc16(frame) == True

    print(f"  面板读取帧: {frame.hex()}")
    print("  PASS: 面板寄存器读取帧构造")


def test_build_write_single():
    """测试写单个寄存器帧构造"""
    # 协议文档4.2示例: 向从站1的寄存器0x1000写入0x0002
    frame = build_write_single(0x01, 0x1000, 0x0002)

    assert frame[0] == 0x01
    assert frame[1] == 0x06
    assert frame[2] == 0x10
    assert frame[3] == 0x00
    assert frame[4] == 0x00
    assert frame[5] == 0x02
    assert verify_crc16(frame) == True

    print(f"  写单个帧: {frame.hex()}")
    print("  PASS: 写单个寄存器帧构造")


def test_build_write_multiple():
    """测试写多个寄存器帧构造"""
    # 协议文档4.3示例: 向从站1的寄存器0x000D写入2个字(0x0100, 0x00AA)
    frame = build_write_multiple(0x01, 0x000D, [0x0100, 0x00AA])

    assert frame[0] == 0x01
    assert frame[1] == 0x10
    assert struct.unpack(">H", frame[2:4])[0] == 0x000D
    assert struct.unpack(">H", frame[4:6])[0] == 0x0002  # 2个寄存器
    assert frame[6] == 0x04  # 4字节数据
    assert struct.unpack(">H", frame[7:9])[0] == 0x0100
    assert struct.unpack(">H", frame[9:11])[0] == 0x00AA
    assert verify_crc16(frame) == True

    print(f"  写多个帧: {frame.hex()}")
    print("  PASS: 写多个寄存器帧构造")


# ============================================================
# 响应解析测试
# ============================================================

def test_parse_read_response():
    """测试读响应解析"""
    # 协议文档4.1示例响应: 01 03 04 01 00 00 AA CRC CRC
    payload = bytes([0x01, 0x03, 0x04, 0x01, 0x00, 0x00, 0xAA])
    frame = append_crc16(payload)

    values = parse_read_response(frame, 0x01)
    assert len(values) == 2
    assert values[0] == 0x0100  # 256
    assert values[1] == 0x00AA  # 170

    print(f"  解析结果: {values}")
    print("  PASS: 读响应解析")


def test_parse_read_response_20regs():
    """测试20个寄存器的读响应解析"""
    # 构造20个寄存器的模拟响应
    slave = 0x01
    byte_count = 40  # 20 * 2
    data = bytes([slave, 0x03, byte_count])

    # 模拟寄存器值: 2202-2221
    reg_values = [
        0x0302,  # 2202: 运行档位=3, 点动档位=2
        0x0000, 0x0064,  # 2203-2204: 织布数=100
        0x0005,  # 2205: 清车数=5
        0x0001,  # 2206: 班别=1(A班)
        0x0000, 0x0032,  # 2207-2208: A班数=50
        0x0000, 0x001E,  # 2209-2210: B班数=30
        0x0000, 0x000A,  # 2211-2212: C班数=10
        0x0002,  # 2213: 喷油模式=2
        0x0001, 0x0000,  # 2214-2215: 织布总数=65536
        0x0406,  # 2216: 运行状态 (高:风扇=1, 低:运行=1,停止=1)
        0x0000,  # 2217: 无故障
        0x03E8,  # 2218: 转速=1000 -> 实际100.0
        0x0064,  # 2219: 纱长1=100 -> 实际10.0
        0x00C8,  # 2220: 纱长2=200 -> 实际20.0
        0x012C,  # 2221: 纱长3=300 -> 实际30.0
    ]
    for v in reg_values:
        data += struct.pack(">H", v)

    frame = append_crc16(data)
    values = parse_read_response(frame, slave)

    assert len(values) == 20
    print(f"  20寄存器值: {values}")
    print("  PASS: 20寄存器读响应解析")


def test_parse_write_response():
    """测试写响应解析"""
    # 写单个响应: 原样返回请求
    payload = bytes([0x01, 0x06, 0x10, 0x00, 0x00, 0x02])
    frame = append_crc16(payload)

    addr, val = parse_write_response(frame, 0x01)
    assert addr == 0x1000
    assert val == 0x0002
    print("  PASS: 写响应解析")


def test_parse_exception():
    """测试异常响应解析"""
    # 异常响应: 从站1, 功能码0x83(0x03+0x80), 异常码0x02(非法地址)
    payload = bytes([0x01, 0x83, 0x02])
    frame = append_crc16(payload)

    try:
        parse_read_response(frame, 0x01)
        assert False, "应该抛出ModbusException"
    except ModbusException as e:
        assert e.function_code == 0x03
        assert e.exception_code == 0x02
        print(f"  异常信息: {e}")
        print("  PASS: 异常响应解析")


# ============================================================
# 预期响应长度测试
# ============================================================

def test_expected_response_length():
    """测试推算响应帧长度"""
    # 读20个寄存器
    req = build_read_holding(0x01, 0x089A, 20)
    expected = get_expected_response_length(req)
    # 1(地址) + 1(功能码) + 1(字节数) + 40(数据) + 2(CRC) = 45
    assert expected == 45, f"期望45, 实际{expected}"

    # 读2个寄存器
    req2 = build_read_holding(0x01, 0x000D, 2)
    expected2 = get_expected_response_length(req2)
    # 1 + 1 + 1 + 4 + 2 = 9
    assert expected2 == 9

    # 写单个
    req3 = build_write_single(0x01, 0x1000, 0x0002)
    assert get_expected_response_length(req3) == 8

    # 写多个
    req4 = build_write_multiple(0x01, 0x000D, [0x0100, 0x00AA])
    assert get_expected_response_length(req4) == 8

    print("  PASS: 预期响应长度推算")


# ============================================================
# 寄存器解析测试
# ============================================================

def test_parse_registers():
    """测试完整寄存器解析"""
    # 20个模拟寄存器值
    values = [
        0x0302,  # 运行档位=3, 点动=2
        0x0000, 0x0064,  # 织布数=100
        0x0005,  # 清车数=5
        0x0001,  # 班别=A班
        0x0000, 0x0032,  # A班=50
        0x0000, 0x001E,  # B班=30
        0x0000, 0x000A,  # C班=10
        0x0002,  # 喷油模式=2
        0x0001, 0x0000,  # 织布总数=65536
        0x0406,  # 运行状态: 高=风扇, 低=运行+停止
        0x0000,  # 无故障
        0x03E8,  # 转速=1000/10=100.0
        0x0064,  # 纱长1=100/10=10.0
        0x00C8,  # 纱长2=200/10=20.0
        0x012C,  # 纱长3=300/10=30.0
    ]

    data = parse_registers(values)

    # 基本数据
    assert data["current_gear_run"] == 3
    assert data["current_gear_jog"] == 2
    assert data["fabric_count"] == 100
    assert data["clean_count"] == 5
    assert data["shift"] == 1
    assert data["shift_a"] == 50
    assert data["shift_b"] == 30
    assert data["shift_c"] == 10
    assert data["oil_mode"] == 2
    assert data["fabric_total"] == 65536

    # 速度/纱长
    assert data["speed"] == 100.0
    assert data["yarn_len_1"] == 10.0
    assert data["yarn_len_2"] == 20.0
    assert data["yarn_len_3"] == 30.0

    # 运行状态位域
    # 0x0406: 高字节=0x04(bit2=马达), 低字节=0x06(bit2=运行, bit1=停止)
    assert data["rs_motor"] == True
    assert data["rs_running"] == True
    assert data["rs_stopped"] == True
    assert data["rs_fan"] == False
    assert data["rs_jogging"] == False

    # 运行模式
    mode = get_run_mode(data)
    assert mode == "running"

    # 故障
    faults = get_active_faults(data)
    assert len(faults) == 0

    print(f"  解析数据: 转速={data['speed']}, 织布={data['fabric_count']}")
    print(f"  运行模式: {mode}")
    print("  PASS: 完整寄存器解析")


def test_parse_fault_status():
    """测试故障状态位域解析"""
    values = [0] * 20
    # 设置故障状态: 超速 + 缺气 + 上断纱
    # 高字节: bit5=超速 -> 0x20
    # 低字节: bit5=缺气 + bit0=上断纱 -> 0x21
    values[15] = (0x20 << 8) | 0x21

    data = parse_registers(values)

    assert data["ft_overspeed"] == True
    assert data["ft_no_air"] == True
    assert data["ft_yarn_break_upper"] == True
    assert data["ft_safety_door"] == False
    assert data["ft_fuse"] == False

    faults = get_active_faults(data)
    assert "超速" in faults
    assert "缺气" in faults
    assert "上断纱" in faults
    assert len(faults) == 3

    print(f"  活跃故障: {faults}")
    print("  PASS: 故障状态位域解析")


# ============================================================
# 参数校验测试
# ============================================================

def test_invalid_params():
    """测试参数校验"""
    errors = []

    # 从站地址超范围
    try:
        build_read_holding(0, 0, 1)
        errors.append("从站地址0应该报错")
    except ValueError:
        pass

    try:
        build_read_holding(248, 0, 1)
        errors.append("从站地址248应该报错")
    except ValueError:
        pass

    # 寄存器数量超范围
    try:
        build_read_holding(1, 0, 0)
        errors.append("寄存器数量0应该报错")
    except ValueError:
        pass

    try:
        build_read_holding(1, 0, 126)
        errors.append("寄存器数量126应该报错")
    except ValueError:
        pass

    # 写入值超范围
    try:
        build_write_single(1, 0, -1)
        errors.append("负值应该报错")
    except ValueError:
        pass

    try:
        build_write_single(1, 0, 0x10000)
        errors.append("超65535应该报错")
    except ValueError:
        pass

    assert len(errors) == 0, f"参数校验失败: {errors}"
    print("  PASS: 参数校验")


# ============================================================
# 运行所有测试
# ============================================================

def run_all_tests():
    """运行所有测试"""
    tests = [
        ("CRC16标准测试向量", test_crc16_known_values),
        ("CRC追加和校验", test_crc16_append_verify),
        ("损坏帧CRC校验", test_crc16_verify_corrupt),
        ("读保持寄存器帧构造", test_build_read_holding),
        ("面板寄存器读取帧构造", test_build_read_holding_panel_regs),
        ("写单个寄存器帧构造", test_build_write_single),
        ("写多个寄存器帧构造", test_build_write_multiple),
        ("读响应解析", test_parse_read_response),
        ("20寄存器读响应解析", test_parse_read_response_20regs),
        ("写响应解析", test_parse_write_response),
        ("异常响应解析", test_parse_exception),
        ("预期响应长度推算", test_expected_response_length),
        ("完整寄存器解析", test_parse_registers),
        ("故障状态位域解析", test_parse_fault_status),
        ("参数校验", test_invalid_params),
    ]

    print("\n" + "=" * 60)
    print("  PLC采集系统 — 单元测试")
    print("=" * 60)

    passed = 0
    failed = 0

    for name, test_func in tests:
        print(f"\n[TEST] {name}")
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 个测试")
    print("=" * 60 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
