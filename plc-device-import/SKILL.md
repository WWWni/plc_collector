---
name: plc-device-import
description: 将Modbus设备协议文档转换为device_type_def表记录，导入PLC采集系统。当用户需要添加新设备类型、解析设备协议文档、配置Modbus寄存器映射时使用此技能。适用于圆机、计米器、温控器等任何Modbus RTU/TCP设备。
version: 1.1.0
---

# PLC 设备协议导入

将设备协议文档转换为 `device_type_def` 表的一行记录。转换完成后采集程序无需改代码即可适配新设备。

## 工作流程

```
1. 读取协议文档 → 2. 提取寄存器表 → 3. 构建定义字典 → 4. 验证 → 5. 写入数据库
```

### Step 1: 分析协议文档

从协议文档中提取以下关键信息：

- **寄存器地址表**：每个寄存器的地址、名称、数据类型、读写权限
- **位域定义**：哪些寄存器的各个 bit 代表什么含义
- **数据编码**：大小端、有符号/无符号、缩放因子、小数点位
- **状态/故障映射**：哪些位或值对应运行状态和故障代码
- **通信参数**：波特率、数据位、停止位（这些在 config.yaml 的 server 层配置，不在本表中）

### Step 2: 确定读取模式

根据寄存器地址是否连续选择读取模式：

| 模式 | 条件 | 配置 |
|------|------|------|
| `contiguous` | 地址连续（如 2202-2221） | `reg_base` + `reg_count` |
| `grouped` | 地址分散（如 0x3E-0x3F 和 0xC0-0xC2） | `read_groups: [{"start":N,"count":N},...]` |

同时需要确定读取功能码类型：

| read_function | 功能码 | 说明 |
|---------------|--------|------|
| `holding`（默认） | 0x03 | 读保持寄存器，绝大多数设备使用此功能码 |
| `input` | 0x04 | 读输入寄存器，少数设备仅支持 0x04（需协议文档明确标注） |

> **⚠ 如何判断该用哪个？**
> - 协议文档中标注 "读保持寄存器" 或 "03H" → `holding`
> - 协议文档中标注 "读输入寄存器" 或 "04H" → `input`
> - 如果文档只列了 03H 但实际设备返回 `exception_code=1`（非法功能码），**不要直接改为 `input`** — 更常见的原因是设备固件对特定寄存器或读取数量有限制，而非功能码本身不被支持。需要排查具体是哪个寄存器/读取量被拒绝（见下方排障指南）
> - 两种功能码的寄存器地址和响应格式完全相同，只是功能码不同

> **⚠ read_groups 分组排障指南（重要实践经验）**
>
> 部分国产仪表固件对 Modbus 读取有额外限制，即使协议文档声称支持，实际也可能拒绝某些读取方式。常见限制：
>
> 1. **不支持跨参数读取**：即使两个寄存器地址连续（如 3EH 和 3FH），也不能一次读 2 个 word。表现为 `exception_code=1`（非法功能码）。
> 2. **限制单次读取数量**：即使文档说某地址允许读 3 个 word，固件可能只允许读 2 个。表现为 `exception_code=3`（在部分设备中含义为"非法寄存器数量"，而非标准 Modbus 的"非法数据值"）。
> 3. **部分寄存器不可读**：某些参数地址虽然文档标注为"读写"，但固件实际拒绝读取。表现为 `exception_code=1`。
>
> **排查方法**：从最简单的读取开始（单个寄存器、count=1），逐步增加范围，通过日志中的 TX/RX 报文和异常码定位被拒绝的寄存器或读取量。最终配置只保留能成功读取的寄存器。
>
> **⚠ 注意非标准异常码定义**：部分设备（如 N90SC 计米器）的异常码定义与标准 Modbus 不同：
>
> | 异常码 | 标准 Modbus | N90SC 等国产仪表 |
> |--------|------------|-----------------|
> | 01H | 非法功能码 | 非法功能码 |
> | 02H | 非法数据地址 | 非法寄存器地址 |
> | 03H | 非法数据值 | **非法寄存器数量** |
> | 04H | 从站设备故障 | **非法数据值** |
>
> 日志中显示的异常码含义可能因设备品牌而异，需参考具体设备的协议文档。

### Step 3: 构建定义字典

按以下字段逐一填写。所有字段说明和完整示例见 [examples.md](examples.md)。

#### 基础信息

```json
{
  "device_type": "my_device",          // 唯一标识，英文+下划线
  "display_name": "我的设备",           // 中文显示名
  "default_name_prefix": "设备"        // 添加设备时的默认前缀
}
```

#### registers — 寄存器清单

```json
// 每个寄存器一条，idx 是扁平索引（从 0 开始连续编号）
[{"idx": 0, "name": "speed", "addr": 100, "desc": "转速"}]
```

**idx 编号规则：**
- `contiguous` 模式：按地址顺序 0, 1, 2, ...
- `grouped` 模式：group_0 的第一个寄存器 idx=0，第二个 idx=1... group_1 接着编号

#### parse_rules — 解析规则（核心）

8 种操作类型，按协议需要选用：

| op | 用途 | 必需参数 | 示例 |
|----|------|----------|------|
| `direct` | 直接取值 | `src_idx` | `{"op":"direct","src_idx":3}` |
| `byte_split` | 拆分高低字节 | `src_idx`, `byte`("high"/"low") | `{"op":"byte_split","src_idx":0,"byte":"high"}` |
| `combine32` | 两个 16 位合并为 32 位无符号 | `src_indices: [hi_idx, lo_idx]` | `{"op":"combine32","src_indices":[1,2]}` |
| `combine32_signed` | 合并为 32 位有符号 | `src_indices` | 同上，MSB 为符号位 |
| `combine32_signed_decimal` | 有符号 + 动态小数点 | `src_indices`, `decimal_field` | `{"op":"combine32_signed_decimal","src_indices":[2,3],"decimal_field":"decimal_point"}` |
| `scale` | 乘以缩放因子 | `src_idx`, `factor` | `{"op":"scale","src_idx":16,"factor":0.1}` |
| `bitfield` | 提取指定位 | `src_idx`, `bit`, `byte`(可选) | `{"op":"bitfield","src_idx":14,"bit":2,"byte":"low"}` |
| `value_map` | 枚举映射 | `src_idx`, `map_name`, `raw_field`(可选) | `{"op":"value_map","src_idx":0,"map_name":"unit_map","raw_field":"unit"}` |

**规则顺序很重要**：如果规则之间有依赖（如 `value_map` 的 `raw_field` 引用了前面 `direct` 的输出），前面的规则必须先执行。`combine32_signed_decimal` 的 `decimal_field` 也必须在前面的规则中已解析。

#### bit_fields — 位域批量解析

当一个寄存器的多个 bit 各有含义时，用此字段批量定义（比逐条写 `bitfield` 规则简洁得多）：

```json
[{
  "src_idx": 14,
  "byte": "high",          // "high"=高字节, "low"=低字节
  "prefix": "rs_",         // 生成字段名的前缀
  "bits": {
    "7": {"name": "force", "label": "强迫"},
    "0": {"name": "jog",   "label": "点动"}
  }
}]
```

生成的字段名为 `{prefix}{name}`，如 `rs_force`、`rs_jog`，值为布尔型。

#### run_mode_rules — 运行模式判断

按优先级从高到低排列，第一个匹配的生效：

```json
// 布尔字段判断（字段为 True 时匹配）
{"field": "rs_running", "mode": "running"}

// 值比较判断
{"field": "mode", "value": 0, "mode": "counting"}
```

- **有规则但均未匹配**时返回 `"unknown"`（如圆机状态异常）
- **无规则（空数组 `[]`）**时返回 `"online"`，表示采集成功即在线。适用于无法从寄存器判断运行状态的简单设备（如计米器）

#### fault_names — 故障名称

从已解析的布尔字段中提取活跃故障：

```json
[{"key": "ft_overspeed", "label": "超速"}]
```

`key` 必须与 `bit_fields` 或 `parse_rules` 生成的字段名一致。

#### display_fields — UI 显示（默认展示配置）

从已定义的字段中选择**最多 4 条**作为仪表板卡片的默认展示数据。
选择原则：根据行业经验，优先选择最能反映设备运行状态的核心指标（如产量、速度、温度等），而非所有可用字段。

```json
// 普通字段 — 必须包含全部四个属性
{"key": "speed", "label": "转速", "unit": "rpm", "format": ".1f"}
// format 支持: Python格式字符串(".1f"), "s"(字符串), ","(千分位)

// 组合字段（如档位）— key 必须是实际存在的字段，额外需要 fields 数组指定子字段
{"key": "current_gear_run", "label": "档位(运/点)", "unit": "", "format": "gear",
 "fields": ["current_gear_run", "current_gear_jog"]}
// unit 支持: 固定字符串, "dynamic"(从数据中读取), ""(无单位)
```

> **⚠ 必须包含完整元数据（key / label / unit / format，组合字段还需 fields）**
> UI 的展示配置页面（DisplayPage）以 `display_fields` 作为字段列表的主数据源。
> 如果缺少 `unit` 或 `format`，用户在 UI 中勾选该字段后保存到 config.yaml 的条目也会缺失这些属性，导致仪表板卡片渲染时格式错误（数值显示为原始字符串、单位丢失等）。
>
> **⚠ 自定义 format（如 gear）的注意事项：**
> `key` 必须指向 parse_rules 中实际产生的字段名（否则 value 为 None，卡片显示 "—"）。
> 如果 format handler 需要从 data 中读取多个子字段（如 gear 读取运行档位和点动档位），必须通过 `fields` 数组声明子字段名。
> `parse_rules` 和 `bit_fields` 中产生的字段仅作为补充来源，不包含 unit/format/fields 信息。

此定义为设备类型级别的默认值。用户可在本地 config.yaml 中按设备实例自定义覆盖。

#### status_map — 状态颜色/文字

```json
{
  "running": {"color": "#4caf50", "text": "运行中"},
  "stopped": {"color": "#9e9e9e", "text": "停止"}
}
```

key 对应 `run_mode_rules` 中定义的 mode 值。此外系统会自动产生两个隐含状态：
- `"online"`：无 `run_mode_rules` 的设备采集成功时自动使用，建议在 `status_map` 中配置为绿色
- `"offline"`：采集失败时自动使用，建议在 `status_map` 中配置为灰色

> **⚠ 简单设备（无 run_mode_rules）的 status_map 建议配置 `"online"` 而非 `"unknown"`：**
> ```json
> {"online": {"color": "#4caf50", "text": "在线"}, "offline": {"color": "#616161", "text": "离线"}}
> ```

#### value_mappings — 枚举映射表

被 `value_map` 操作引用：

```json
{
  "unit_map": {"0": "米", "1": "码"},
  "mode_map": {"0": "计长", "1": "速度"}
}
```

key 是映射表名，value 是 `{"原始值字符串": "显示文本"}` 的字典。

### Step 4: 验证

构建完成后用以下脚本验证：

```python
from protocol.generic_parser import GenericParser
parser = GenericParser(type_def_dict)

# 模拟寄存器值（全 0 或已知值）
test_values = [0] * parser.REG_COUNT  # contiguous
# 或 {"group_0": [0,0], "group_1": [0,0,0]}  # grouped

result = parser.parse_registers(test_values)
print(f"解析字段: {list(result.keys())}")
print(f"运行模式: {parser.get_run_mode(result)}")
print(f"活跃故障: {parser.get_active_faults(result)}")
```

**检查清单：**
- [ ] `read_function` 已根据设备实际固件确认（默认 `holding`）
- [ ] `read_groups` 的每个分组已验证可被设备接受（注意：部分设备不支持跨参数读取或限制单次读取数量，需通过实际通信测试确认）
- [ ] 所有 parse_rules 中的 `src_idx` 不超过寄存器数量
- [ ] `combine32` / `combine32_signed` 的 `src_indices` 中两个 idx 都存在
- [ ] `bit_fields` 中的 `prefix` + `name` 与 `fault_names` 的 `key` 对应
- [ ] `run_mode_rules` 引用的字段在 `bit_fields` 或 `parse_rules` 中有定义
- [ ] `display_fields` 的 `key` 都是已解析出的字段名
- [ ] `display_fields` 每条都包含完整的 key/label/unit/format 四个属性
- [ ] `value_mappings` 的 key 与 `value_map` 规则的 `map_name` 对应

### Step 5: 写入数据库

使用项目 config.yaml 中的数据库连接配置。脚本会自动检查 device_type_def 表是否存在、字段是否完整，缺什么补什么。

```python
import os, sys

# 定位项目根目录
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from config_loader import load_config, get_db_url
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from storage.models import DeviceTypeDef
from protocol.device_types import load_from_db, save_cache

# 从 config.yaml 读取数据库连接配置
config = load_config(os.path.join(project_root, 'config.yaml'))
url = get_db_url(config.database)
engine = create_engine(url)

# ---- 检查/创建 device_type_def 表 ----
inspector = inspect(engine)
if not inspector.has_table("device_type_def"):
    # 表不存在，创建
    DeviceTypeDef.__table__.create(engine)
    print("已创建 device_type_def 表")
else:
    # 表存在，检查字段是否完整
    existing_cols = {col["name"] for col in inspector.get_columns("device_type_def")}
    model_cols = {col.name for col in DeviceTypeDef.__table__.columns}
    missing = model_cols - existing_cols
    if missing:
        for col_name in missing:
            col = DeviceTypeDef.__table__.columns[col_name]
            col_type = col.type.compile(engine.dialect)
            nullable = "NULL" if col.nullable else "NOT NULL"
            default = f"DEFAULT {col.default.arg}" if col.default else ""
            sql = f"ALTER TABLE device_type_def ADD COLUMN {col_name} {col_type} {nullable} {default}"
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
        print(f"已补充缺失字段: {missing}")
    else:
        print("device_type_def 表结构完整")

# ---- 插入或更新设备定义 ----
Session = sessionmaker(bind=engine)
with Session() as session:
    existing = session.query(DeviceTypeDef).filter_by(
        device_type=type_def_dict["device_type"]
    ).first()
    if existing:
        for k, v in type_def_dict.items():
            setattr(existing, k, v)
        print(f"已更新: {type_def_dict['device_type']}")
    else:
        session.add(DeviceTypeDef(**type_def_dict))
        print(f"已新增: {type_def_dict['device_type']}")
    session.commit()

# ---- 刷新注册表 + 保存缓存 ----
session_factory = sessionmaker(bind=engine, expire_on_commit=False)
n = load_from_db(session_factory)
config_dir = os.path.dirname(os.path.abspath(
    os.path.join(project_root, 'config.yaml')
))
save_cache(config_dir)
engine.dispose()
print(f"Done — 已加载 {n} 个设备类型")
```
