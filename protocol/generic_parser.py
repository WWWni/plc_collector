"""
通用设备协议解析引擎
=====================
从 device_type_def 表行数据构建解析器，实现与旧设备模块完全相同的接口。
支持 7 种解析操作: direct, byte_split, combine32, combine32_signed,
                  combine32_signed_decimal, scale, bitfield, value_map。

新设备只需在数据库中配置 parse_rules / bit_fields 等 JSON 即可，无需写代码。
"""

from typing import Dict, Any, List, Optional


class GenericParser:
    """
    通用设备协议解析器

    接收 device_type_def 表的一行数据（dict 或 ORM 对象），
    对外暴露与旧 protocol.devices.* 模块相同的属性接口:
        DEVICE_TYPE, DISPLAY_NAME, DEFAULT_NAME_PREFIX,
        DISPLAY_FIELDS, STATUS_MAP,
        REG_BASE / REG_COUNT 或 READ_GROUPS,
        parse_registers(values), get_run_mode(data), get_active_faults(data)
    """

    def __init__(self, type_def: dict):
        """
        Args:
            type_def: device_type_def 表行，可以是 dict 或 ORM 对象
        """
        self.DEVICE_TYPE = type_def["device_type"]
        self.DISPLAY_NAME = type_def["display_name"]
        self.DEFAULT_NAME_PREFIX = type_def.get("default_name_prefix", "设备")

        # 寄存器读取方式
        self._read_mode = type_def["read_mode"]
        if self._read_mode == "contiguous":
            self.REG_BASE = type_def["reg_base"]
            self.REG_COUNT = type_def["reg_count"]
        else:
            self.READ_GROUPS = type_def["read_groups"]

        # 解析配置
        self._registers = type_def.get("registers") or []
        self._parse_rules = type_def.get("parse_rules") or []
        self._bit_fields = type_def.get("bit_fields") or []
        self._run_mode_rules = type_def.get("run_mode_rules") or []
        self._fault_names = type_def.get("fault_names") or []
        self._value_mappings = type_def.get("value_mappings") or {}

        # UI 配置
        self.DISPLAY_FIELDS = type_def.get("display_fields") or []
        self.STATUS_MAP = type_def.get("status_map") or {}

    # ---- 核心解析方法 ----

    def parse_registers(self, values) -> Dict[str, Any]:
        """
        解析寄存器原始值为结构化数据

        Args:
            values: contiguous 模式为 list[int];
                    grouped 模式为 dict {"group_0": [int,...], "group_1": [...]}

        Returns:
            解析后的数据字典
        """
        # 统一为扁平列表
        flat = self._flatten_values(values)

        result = {}

        # 1. 执行位域解析 (生成多个布尔字段 + 保存 raw 值)
        for bf_def in self._bit_fields:
            src_idx = bf_def["src_idx"]
            byte_pos = bf_def.get("byte", "low")  # "high" or "low"
            prefix = bf_def.get("prefix", "")
            bits = bf_def.get("bits", {})

            raw_value = flat[src_idx] if src_idx < len(flat) else 0
            result[f"{prefix.rstrip('_')}_raw"] = raw_value  # e.g. run_status_raw

            if byte_pos == "high":
                byte_val = (raw_value >> 8) & 0xFF
            else:
                byte_val = raw_value & 0xFF

            for bit_str, bit_def in bits.items():
                bit_pos = int(bit_str)
                field_name = f"{prefix}{bit_def['name']}"
                result[field_name] = bool((byte_val >> bit_pos) & 1)

        # 2. 执行解析规则
        for rule in self._parse_rules:
            op = rule["op"]
            field = rule["field"]

            if op == "direct":
                result[field] = flat[rule["src_idx"]] if rule["src_idx"] < len(flat) else 0

            elif op == "byte_split":
                raw = flat[rule["src_idx"]] if rule["src_idx"] < len(flat) else 0
                if rule["byte"] == "high":
                    result[field] = (raw >> 8) & 0xFF
                else:
                    result[field] = raw & 0xFF

            elif op == "combine32":
                hi_idx, lo_idx = rule["src_indices"]
                hi = flat[hi_idx] if hi_idx < len(flat) else 0
                lo = flat[lo_idx] if lo_idx < len(flat) else 0
                result[field] = (hi << 16) | lo

            elif op == "combine32_signed":
                hi_idx, lo_idx = rule["src_indices"]
                hi = flat[hi_idx] if hi_idx < len(flat) else 0
                lo = flat[lo_idx] if lo_idx < len(flat) else 0
                raw = (hi << 16) | lo
                result[field] = self._to_signed_32(raw)

            elif op == "combine32_signed_decimal":
                hi_idx, lo_idx = rule["src_indices"]
                hi = flat[hi_idx] if hi_idx < len(flat) else 0
                lo = flat[lo_idx] if lo_idx < len(flat) else 0
                raw = (hi << 16) | lo
                signed = self._to_signed_32(raw)

                # 小数点位来自另一个已解析的字段
                dec_field = rule["decimal_field"]
                decimal_point = result.get(dec_field, 0)
                decimal_point = max(0, min(decimal_point, 4))

                result[field] = signed / (10 ** decimal_point) if decimal_point > 0 else float(signed)

            elif op == "scale":
                raw = flat[rule["src_idx"]] if rule["src_idx"] < len(flat) else 0
                result[field] = raw * rule["factor"]

            elif op == "value_map":
                raw = flat[rule["src_idx"]] if rule["src_idx"] < len(flat) else 0
                map_name = rule["map_name"]
                mapping = self._value_mappings.get(map_name, {})
                result[field] = mapping.get(str(raw), str(raw))
                # 同时保存原始值
                raw_field = rule.get("raw_field", field.replace("_text", ""))
                if raw_field != field:
                    result[raw_field] = raw

        return result

    def get_run_mode(self, parsed_data: Dict[str, Any]) -> str:
        """根据 run_mode_rules 判断运行模式"""
        for rule in self._run_mode_rules:
            field = rule["field"]
            expected = rule.get("value")  # None 表示 True (布尔字段)

            if expected is None:
                # 布尔字段: 为 True 时匹配
                if parsed_data.get(field, False):
                    return rule["mode"]
            else:
                # 值比较
                if parsed_data.get(field) == expected:
                    return rule["mode"]
        return "unknown"

    def get_active_faults(self, parsed_data: Dict[str, Any]) -> List[str]:
        """从 fault_names 定义中提取活跃故障"""
        active = []
        for fn in self._fault_names:
            if parsed_data.get(fn["key"], False):
                active.append(fn["label"])
        return active

    # ---- 辅助方法 ----

    @staticmethod
    def _to_signed_32(raw: int) -> int:
        """32位无符号转有符号 (MSB符号位+补码)"""
        if raw >= 0x80000000:
            return raw - 0x100000000
        return raw

    def _flatten_values(self, values) -> list:
        """
        将寄存器值统一为扁平列表

        contiguous 模式: values 已经是 list，直接返回
        grouped 模式: values 是 dict，按 group_0, group_1, ... 顺序拼接
        """
        if isinstance(values, list):
            return values
        # grouped: 按组号顺序拼接
        flat = []
        i = 0
        while True:
            key = f"group_{i}"
            if key not in values:
                break
            flat.extend(values[key])
            i += 1
        return flat
