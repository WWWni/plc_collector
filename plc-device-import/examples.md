# 设备定义参考示例

两个已实现的设备类型定义，可作为新设备的模板。

## 示例 1: 圆机面板（contiguous 模式）

特点：20 个连续寄存器、4 组位域（32 个布尔字段）、运行/故障状态判断。

```json
{
  "device_type": "weaving_panel",
  "display_name": "圆机面板",
  "default_name_prefix": "圆机",

  "read_mode": "contiguous",
  "reg_base": 2202,
  "reg_count": 20,
  "read_groups": null,
  "read_function": "holding",

  "registers": [
    {"idx": 0,  "name": "current_gear",   "addr": 2202, "desc": "当前档位"},
    {"idx": 1,  "name": "fabric_count_h",  "addr": 2203, "desc": "织布数高位"},
    {"idx": 2,  "name": "fabric_count_l",  "addr": 2204, "desc": "织布数低位"},
    {"idx": 3,  "name": "clean_count",     "addr": 2205, "desc": "清车数"},
    {"idx": 4,  "name": "shift",           "addr": 2206, "desc": "班别"},
    {"idx": 5,  "name": "shift_a_h",       "addr": 2207, "desc": "A班数高位"},
    {"idx": 6,  "name": "shift_a_l",       "addr": 2208, "desc": "A班数低位"},
    {"idx": 7,  "name": "shift_b_h",       "addr": 2209, "desc": "B班数高位"},
    {"idx": 8,  "name": "shift_b_l",       "addr": 2210, "desc": "B班数低位"},
    {"idx": 9,  "name": "shift_c_h",       "addr": 2211, "desc": "C班数高位"},
    {"idx": 10, "name": "shift_c_l",       "addr": 2212, "desc": "C班数低位"},
    {"idx": 11, "name": "oil_mode",        "addr": 2213, "desc": "喷油模式"},
    {"idx": 12, "name": "fabric_total_h",  "addr": 2214, "desc": "织布总数高位"},
    {"idx": 13, "name": "fabric_total_l",  "addr": 2215, "desc": "织布总数低位"},
    {"idx": 14, "name": "run_status",      "addr": 2216, "desc": "运行状态位域"},
    {"idx": 15, "name": "fault_status",    "addr": 2217, "desc": "故障状态位域"},
    {"idx": 16, "name": "speed",           "addr": 2218, "desc": "转速(值*10)"},
    {"idx": 17, "name": "yarn_len_1",      "addr": 2219, "desc": "纱长1(值*10)"},
    {"idx": 18, "name": "yarn_len_2",      "addr": 2220, "desc": "纱长2(值*10)"},
    {"idx": 19, "name": "yarn_len_3",      "addr": 2221, "desc": "纱长3(值*10)"}
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
    {"field": "yarn_len_3",       "op": "scale",      "src_idx": 19, "factor": 0.1}
  ],

  "bit_fields": [
    {
      "src_idx": 14, "byte": "high", "prefix": "rs_",
      "bits": {
        "7": {"name": "force",       "label": "强迫"},
        "6": {"name": "clean",       "label": "清车"},
        "5": {"name": "fan",         "label": "风扇"},
        "4": {"name": "cloth_watch", "label": "照布"},
        "3": {"name": "lighting",    "label": "照明"},
        "2": {"name": "motor",       "label": "马达"},
        "1": {"name": "lighting2",   "label": "照明2"},
        "0": {"name": "oil_pump",    "label": "油泵"}
      }
    },
    {
      "src_idx": 14, "byte": "low", "prefix": "rs_",
      "bits": {
        "7": {"name": "shift_c",     "label": "班别C"},
        "6": {"name": "shift_b",     "label": "班别B"},
        "5": {"name": "shift_a",     "label": "班别A"},
        "4": {"name": "needle_drive","label": "针驱"},
        "3": {"name": "oil_drive",   "label": "油驱"},
        "2": {"name": "running",     "label": "运行"},
        "1": {"name": "stopped",     "label": "停止"},
        "0": {"name": "jogging",     "label": "点动"}
      }
    },
    {
      "src_idx": 15, "byte": "high", "prefix": "ft_",
      "bits": {
        "7": {"name": "fabric_complete", "label": "织布完成"},
        "6": {"name": "clean_complete",  "label": "清车完成"},
        "5": {"name": "overspeed",       "label": "超速"},
        "4": {"name": "stop_key",        "label": "停止键"},
        "3": {"name": "over_force",      "label": "超强迫"},
        "2": {"name": "force_oil",       "label": "强迫喷油"},
        "1": {"name": "force_fan",       "label": "强迫风扇"},
        "0": {"name": "fuse",            "label": "保险丝"}
      }
    },
    {
      "src_idx": 15, "byte": "low", "prefix": "ft_",
      "bits": {
        "7": {"name": "safety_door",      "label": "安全门"},
        "6": {"name": "inverter",         "label": "变频器"},
        "5": {"name": "no_air",           "label": "缺气"},
        "4": {"name": "no_oil",           "label": "缺油"},
        "3": {"name": "fabric_break",     "label": "破布"},
        "2": {"name": "probe",            "label": "探针"},
        "1": {"name": "yarn_break_lower", "label": "下断纱"},
        "0": {"name": "yarn_break_upper", "label": "上断纱"}
      }
    }
  ],

  "run_mode_rules": [
    {"field": "rs_running", "mode": "running"},
    {"field": "rs_jogging", "mode": "jogging"},
    {"field": "rs_stopped", "mode": "stopped"}
  ],

  "fault_names": [
    {"key": "ft_fabric_complete",  "label": "织布完成"},
    {"key": "ft_clean_complete",   "label": "清车完成"},
    {"key": "ft_overspeed",        "label": "超速"},
    {"key": "ft_stop_key",         "label": "停止键"},
    {"key": "ft_over_force",       "label": "超强迫"},
    {"key": "ft_force_oil",        "label": "强迫喷油"},
    {"key": "ft_force_fan",        "label": "强迫风扇"},
    {"key": "ft_fuse",             "label": "保险丝"},
    {"key": "ft_safety_door",      "label": "安全门"},
    {"key": "ft_inverter",         "label": "变频器"},
    {"key": "ft_no_air",           "label": "缺气"},
    {"key": "ft_no_oil",           "label": "缺油"},
    {"key": "ft_fabric_break",     "label": "破布"},
    {"key": "ft_probe",            "label": "探针"},
    {"key": "ft_yarn_break_lower", "label": "下断纱"},
    {"key": "ft_yarn_break_upper", "label": "上断纱"}
  ],

  "display_fields": [
    {"key": "speed",        "label": "转速",       "unit": "rpm", "format": ".1f"},
    {"key": "fabric_count", "label": "织布数",     "unit": "",    "format": ","},
    {"key": "fabric_total", "label": "织布总数",   "unit": "",    "format": ","},
    {"key": "gear",         "label": "档位(运/点)", "unit": "",   "format": "gear"}
  ],

  "status_map": {
    "running": {"color": "#4caf50", "text": "运行中"},
    "jogging": {"color": "#ff9800", "text": "点动"},
    "stopped": {"color": "#9e9e9e", "text": "停止"},
    "fault":   {"color": "#f44336", "text": "故障"},
    "offline": {"color": "#616161", "text": "离线"},
    "unknown": {"color": "#9e9e9e", "text": "未知"}
  },

  "value_mappings": {}
}
```

### 解析规则解读

| 寄存器 | 操作 | 说明 |
|--------|------|------|
| idx 0 (0x0302) | byte_split | 高字节=运行档位(3), 低字节=点动档位(2) |
| idx 1,2 | combine32 | 高位左移16位 + 低位 = 32位无符号整数 |
| idx 16 (1000) | scale * 0.1 | 1000 * 0.1 = 100.0 rpm |
| idx 14 (0x0406) | bit_fields | 高字节 bit2=马达, 低字节 bit2=运行、bit1=停止 |

---

## 示例 2: N90SC-4 计米器（grouped 模式）

特点：非连续地址、分组读取、有符号32位+动态小数点。

> **⚠ 实践经验**：N90SC 固件对读取有严格限制，虽然说明书声称 3EH/3FH（单位/模式）可读、C0H 可一次读 3 个 word，但实际固件会拒绝部分请求。最终配置只保留了可成功读取的 C0H(2 word) 和 C2H(1 word)。详见下方排障记录。

```json
{
  "device_type": "n90sc_counter",
  "display_name": "N90SC-4计米器",
  "default_name_prefix": "计米器",

  "read_mode": "grouped",
  "reg_base": null,
  "reg_count": null,
  "read_function": "holding",
  "read_groups": [
    {"start": 192, "count": 2},
    {"start": 194, "count": 1}
  ],

  "registers": [
    {"idx": 0, "name": "display_h",  "addr": 192, "desc": "显示值高位"},
    {"idx": 1, "name": "display_l",  "addr": 193, "desc": "显示值低位"},
    {"idx": 2, "name": "decimal",    "addr": 194, "desc": "小数点位数(0-4)"}
  ],

  "parse_rules": [
    {"field": "decimal_point", "op": "direct",                  "src_idx": 2},
    {"field": "display_raw",   "op": "combine32_signed",        "src_indices": [0, 1]},
    {"field": "display_value", "op": "combine32_signed_decimal", "src_indices": [0, 1], "decimal_field": "decimal_point"}
  ],

  "bit_fields": null,

  "run_mode_rules": [],

  "fault_names": null,

  "display_fields": [
    {"key": "display_value", "label": "当前值", "unit": "dynamic", "format": ".2f"}
  ],

  "status_map": {
    "online":   {"color": "#4caf50", "text": "在线"},
    "offline":  {"color": "#616161", "text": "离线"}
  },

  "value_mappings": null
}
```

### 解析规则解读

| 寄存器 | 操作 | 说明 |
|--------|------|------|
| idx 0,1 (hi=0, lo=12345) | combine32_signed | (0<<16)\|12345 = 12345 (正数) |
| idx 0,1 + idx 2 (decimal=2) | combine32_signed_decimal | 12345 / 10^2 = 123.45 |
| idx 2 (decimal=2) | direct | 小数点位数，被上面的规则引用 |

### 分组索引对照

```
group_0 (start=0xC0, count=2):  idx 0 (addr 192), idx 1 (addr 193)
group_1 (start=0xC2, count=1):  idx 2 (addr 194)
```

### N90SC 排障记录

N90SC 的固件行为与说明书不完全一致，排查过程中遇到了以下问题：

| 尝试的配置 | 请求帧 | 设备响应 | 异常码 | 原因分析 |
|-----------|--------|---------|--------|---------|
| 3EH, count=2 | `01 03 003E 0002 A5C7` | `01 83 01 80F0` | 01H | 不支持跨参数读取（3EH+3FH） |
| 3EH, count=1 | `01 03 003E 0001 E5C6` | `01 83 01 80F0` | 01H | 3EH 寄存器固件拒绝读取 |
| 3FH, count=1 | `01 03 003F 0001 B406` | （未测试，预计同样拒绝） | — | 同上 |
| C0H, count=3 | `01 03 00C0 0003 05F7` | `01 83 03 0131` | 03H | 限制单次读取数量（N90SC的03H=非法寄存器数量） |
| **C0H, count=2** | `01 03 00C0 0002 C437` | 正常响应 | — | ✅ 成功 |
| **C2H, count=1** | `01 03 00C2 0001 25F6` | 正常响应 | — | ✅ 成功 |

**关键结论**：
1. N90SC 的异常码 03H 含义为"非法寄存器数量"（非标准 Modbus 的"非法数据值"）
2. 3EH/3FH 寄存器虽然说明书标注可读，但固件实际拒绝读取
3. C0H 虽然说明书说可读 3 个 word，但固件只允许读 2 个
4. 最终只保留 C0H(2 word) + C2H(1 word) 的读取配置
