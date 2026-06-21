# PLC 面板数据采集系统

基于 ZLAN5143D 串口服务器的工业面板数据采集系统，支持 Modbus TCP 和 TCP 透传两种通信模式，提供 GUI 监控界面和命令行两种运行方式。

## 系统架构

```
面板设备(RS485) ──RS485──> ZLAN5143D ──Ethernet──> 采集程序(Python) ──> MySQL
                                                       │
                                                       ├── monitor_app.py  (GUI 监控+配置)
                                                       └── main.py         (命令行采集)
```

**核心特性：**

- **多串口服务器架构**：每台 ZLAN5143D 独立传输层，互不影响
- **设备类型注册表**：从数据库动态加载设备类型定义，新增设备无需改代码
- **配置驱动采集**：通过 `device_type_def` 表的 JSON 配置定义寄存器映射、解析规则、显示字段
- **GUI 监控界面**：实时数据面板 + 故障告警 + 内置配置管理，支持系统托盘驻留
- **多工控机数据隔离**：通过 `collector_id` 自动隔离不同工控机的数据
- **按天分区存储**：`plc_data` 表按天 RANGE 分区，历史数据通过 `DROP PARTITION` 瞬间清理
- **Nuitka 原生编译**：将 Python 编译为 C++ 原生二进制，双击秒开

## 快速开始

### 1. 安装依赖

```bash
python -m venv my_env
my_env\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置 ZLAN5143D

使用 ZLVircom 工具配置串口服务器参数：

**Modbus TCP 网关模式（默认）：**

| 参数 | 设置值 |
|------|--------|
| 工作模式 | TCP 服务器 |
| 转化协议 | Modbus TCP |
| 端口 | 502 |
| 波特率 | 9600 |

**TCP 透传模式：**

| 参数 | 设置值 |
|------|--------|
| 工作模式 | TCP 服务器 |
| 转化协议 | NONE |
| 端口 | 4196 |
| 波特率 | 9600 |
| 数据位 / 校验 / 停止位 | 8 / 无 / 1 |

### 3. 编辑配置文件

编辑 `config.yaml`：

```yaml
servers:
  - name: 串口服务器1
    connection:
      mode: modbus_tcp            # 或 tcp_transparent
      host: 192.168.1.200
      port: 502
      tcp_timeout: 1              # TCP 连接超时（秒）
    serial:
      baudrate: 9600
    devices:
      - slave_addr: 1
        name: 计米器1
        device_type: n90sc_counter
        # timeout: 0.5            # 可选，覆盖全局 Modbus 超时
        # retry: 2                # 可选，覆盖全局重试次数

scheduler:
  interval_seconds: 4             # 采集间隔（秒）
  timeout: 0.3                    # Modbus 读取超时（秒）
  retry: 1                        # Modbus 读取重试次数
  retry_delay: 0.1                # 重试前等待（秒）

database:
  engine: mysql
  host: 192.168.0.33
  port: 3306
  username: root
  password: '123456'
  database: oldmes
  table_name: plc_data            # 写入表名（可自定义）
```

> **配置优先级**：`devices` 中的 `timeout` / `retry` 为 `None` 时自动回退到 `scheduler` 全局值。

### 4. 运行

**GUI 模式（推荐）：**

```bash
python monitor_app.py                    # 正常模式
python monitor_app.py --test             # 模拟模式（随机数据，无需设备）
python monitor_app.py -c my_config.yaml  # 指定配置文件
python monitor_app.py --auto             # 开机自启（隐藏到托盘，自动开始采集）
```

**命令行模式（无 GUI，仅采集入库）：**

```bash
python main.py                     # 正常采集
python main.py --test              # 测试模式（仅打印，不写库）
python main.py -c my_config.yaml   # 指定配置文件
```

## 项目结构

```
plc_collector/
├── monitor_app.py              # GUI 统一启动入口（采集+监控+配置）
├── main.py                     # 命令行采集入口（无 GUI）
├── config.yaml                 # 配置文件（支持 GUI 界面编辑）
├── config_loader.py            # 配置加载与校验（dataclass 模型）
│
├── protocol/                   # 协议层
│   ├── modbus_rtu.py           #   Modbus RTU 帧构造 / 解析 / CRC16
│   ├── device_types.py         #   设备类型注册表（从 DB 加载 + 本地缓存）
│   └── generic_parser.py       #   通用寄存器解析引擎（8 种操作类型）
│
├── transport/                  # 传输层
│   ├── base.py                 #   抽象基类（read/write registers）
│   ├── tcp_transparent.py      #   TCP 透传模式
│   └── modbus_tcp.py           #   Modbus TCP 网关模式
│
├── collector/                  # 采集层
│   ├── device.py               #   单台设备采集（含 per-device 超时/重试）
│   └── scheduler.py            #   多服务器多设备轮询调度
│
├── storage/                    # 存储层
│   ├── models.py               #   ORM 模型（device_type_def + plc_data）
│   ├── db_manager.py           #   数据库管理（连接/写入/分区清理）
│   └── fault_events.py         #   故障事件持久化
│
├── gui/                        # GUI 层
│   ├── monitor/
│   │   ├── main_window.py      #   监控主窗口（工具栏 + Tab 页 + 托盘 + 单实例）
│   │   ├── dashboard_tab.py    #   实时数据面板（卡片式布局）
│   │   └── alarms_tab.py       #   故障告警面板
│   ├── config/
│   │   ├── main_window.py      #   配置对话框（Tab 式）
│   │   ├── servers_page.py     #   服务器配置页
│   │   ├── devices_page.py     #   设备管理页（含批量添加 / CSV 导入导出）
│   │   ├── database_page.py    #   数据库配置页
│   │   ├── scheduler_page.py   #   调度配置页
│   │   └── display_page.py     #   展示字段配置页
│   └── shared/
│       ├── async_bridge.py     #   qasync 事件循环桥接
│       └── styles.py           #   工业深色主题样式
│
├── utils/
│   ├── logger.py               #   日志配置（滚动文件）
│   └── paths.py                #   路径工具（兼容开发 / PyInstaller / Nuitka onefile）
│
├── plc-device-import/          # AI Skill：设备协议导入
│   ├── SKILL.md                #   技能说明与工作流程
│   └── examples.md             #   两个完整设备定义示例
│
├── build_nuitka.bat            # Nuitka 打包脚本（推荐）
├── build_pyinstaller.bat       # PyInstaller 打包脚本（备选）
├── monitor_app.spec            # PyInstaller 打包配置
└── requirements.txt            # 依赖清单
```

## 数据库设计

### device_type_def（设备类型定义）

每个设备类型一行，存储协议配置、解析规则、显示定义。新增设备类型只需在此表插入新行，采集程序无需改代码。

| 字段 | 说明 |
|------|------|
| `device_type` | 唯一标识（如 `n90sc_counter`） |
| `read_mode` | `contiguous`（连续寄存器）/ `grouped`（分组读取） |
| `registers` | 寄存器地址表 JSON |
| `parse_rules` | 解析规则 JSON（8 种操作：direct / byte_split / combine32 / scale / value_map 等） |
| `bit_fields` | 位域批量解析 JSON |
| `run_mode_rules` | 运行模式判断规则 |
| `display_fields` | 仪表板默认展示字段（最多 4 个） |
| `status_map` | 状态颜色 / 文字映射 |
| `value_mappings` | 枚举值映射表 |

### plc_data（采集数据）

所有设备类型共用，按天 RANGE 分区。`field_data` 列存 JSON 格式的采集字段值。

| 字段 | 说明 |
|------|------|
| `timestamp` | 采集时间（分区键） |
| `collector_id` | 工控机标识（多实例隔离） |
| `server_index` | 串口服务器索引 |
| `slave_addr` | 从站地址 |
| `device_name` | 设备名称 |
| `device_type` | 设备类型标识 |
| `field_data` | 采集数据 JSON |
| `run_mode` | 运行模式 |
| `fault_log` | 故障日志 JSON |

历史数据保留 30 天，通过 `DROP PARTITION` 瞬间完成清理。

### device_registry（设备注册表）

记录所有曾经采集过的设备，`batch_insert` 时自动注册新设备、更新 `last_seen`。

| 字段 | 说明 |
|------|------|
| `device_name` | 设备名称 |
| `device_type` | 设备类型标识 |
| `slave_addr` | 从站地址 |
| `collector_id` | 工控机标识 |
| `server_index` | 串口服务器索引 |
| `first_seen` | 首次采集时间 |
| `last_seen` | 最近采集时间 |

唯一约束：`collector_id` + `slave_addr` 组合唯一。

## 打包发布

提供两种打包方式，输出目录互相隔离：

### Nuitka（推荐 — 秒开）

将 Python 编译为 C++ 原生二进制，启动无解压延迟：

```bash
build_nuitka.bat
```

- 输出：`dist/PLC_Collector_Nuitka/monitor_app.exe`（单文件 ~32MB）
- 需要 MSVC 14.5+（Visual Studio 2022+）
- 首次编译约 5-10 分钟，增量编译秒级完成

### PyInstaller（备选）

```bash
build_pyinstaller.bat
```

- 输出：`dist/PLC_Collector/`（monitor_app.exe + `_internal/` 目录）

两种方式均自动复制 `config.yaml` 到输出目录，整个目录压缩即可分发。

## 添加新设备类型（plc-device-import）

本系统通过 **设备类型注册表** 驱动采集，新增设备类型无需修改代码。项目内置了 `plc-device-import` AI Skill（`plc-device-import.skill` + `plc-device-import/SKILL.md`），可在 Claude Code、Codex、Hermes、OpenCode、Qoder 等 AI 编程工具中通过斜杠命令或手动引用调用，自动完成从协议文档到数据库记录的全流程。

### 何时使用

- 接入一台新类型的 Modbus 设备（圆机、计米器、温控器等）
- 拿到设备厂家的协议文档，需要解析寄存器映射
- 需要调整已有设备的寄存器地址或解析规则

### 使用方法

1. 准备好设备的 Modbus 协议文档（PDF / 图片 / 文本均可）
2. 在 AI 编程工具中输入 `/plc-device-import` 或将 `plc-device-import/SKILL.md` 提供给 AI，附上协议文档
3. Skill 自动完成以下流程：

```
读取协议文档 → 提取寄存器表 → 构建 device_type_def JSON → 验证 → 写入数据库
```

4. 写入后采集程序自动从数据库加载新定义，无需重启

### 定义结构

每条设备类型定义包含以下核心部分：

| 字段 | 作用 |
|------|------|
| `device_type` | 唯一标识（如 `n90sc_counter`） |
| `read_mode` | 寄存器读取模式：`contiguous`（连续）或 `grouped`（分组） |
| `registers` | 寄存器地址表（地址、名称、索引） |
| `parse_rules` | 解析规则（8 种操作：direct / byte_split / combine32 / combine32_signed / combine32_signed_decimal / scale / bitfield / value_map） |
| `bit_fields` | 位域批量解析（一个寄存器的各 bit 含义） |
| `run_mode_rules` | 运行模式判断规则 |
| `fault_names` | 故障名称映射 |
| `display_fields` | 仪表板默认展示字段（最多 4 个） |
| `status_map` | 状态颜色 / 文字映射 |
| `value_mappings` | 枚举值映射表 |

完整的字段说明和两个参考示例（圆机面板 + N90SC 计米器）见 [`plc-device-import/examples.md`](plc-device-import/examples.md)。

## 技术栈

| 组件 | 技术 |
|------|------|
| 通信协议 | pymodbus >= 3.5（Modbus TCP/RTU） |
| 数据库 ORM | SQLAlchemy 2.0 + PyMySQL |
| GUI 框架 | PySide6 >= 6.5 + qasync（asyncio 桥接） |
| 实时图表 | pyqtgraph |
| 配置解析 | PyYAML |
| 打包工具 | Nuitka（MSVC 14.5）/ PyInstaller |
| 运行平台 | Windows x86_64 |

## 许可证

[MIT License](LICENSE)
