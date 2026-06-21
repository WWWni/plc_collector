# PLC面板数据采集系统

基于 ZLAN5143D 串口服务器的工业面板数据采集系统，支持 TCP 透传和 Modbus TCP 两种通信模式，提供 GUI 监控界面和命令行两种运行方式。

## 系统架构

```
面板设备(RS485) ──RS485──> ZLAN5143D ──Ethernet──> 采集程序(Python) ──> MySQL/PostgreSQL
                                                       │
                                                       ├── monitor_app.py  (GUI监控+配置)
                                                       └── main.py         (命令行采集)
```

**核心特性：**
- 多串口服务器架构：每台 ZLAN5143D 独立传输层，互不影响
- 设备类型注册表：从数据库动态加载设备类型定义，支持多种设备混采
- GUI 监控界面：实时数据面板 + 故障告警 + 内置配置管理，单实例运行（支持托盘唤醒）
- 多工控机数据隔离：通过 `collector_id` 自动隔离不同工控机的数据
- Nuitka 原生编译打包：真正的二进制可执行文件，双击秒开

## 快速开始

### 1. 安装依赖

```bash
# 推荐使用虚拟环境
python -m venv my_env
my_env\Scripts\activate

pip install -r requirements.txt
```

### 2. 配置 ZLAN5143D

使用 ZLVircom 工具配置串口服务器参数：

**TCP 透传模式 (推荐):**

| 参数 | 设置值 |
|------|--------|
| 工作模式 | TCP 服务器 |
| 转化协议 | NONE |
| 端口 | 4196 |
| 波特率 | 9600 |
| 数据位 | 8 |
| 校验位 | 无 |
| 停止位 | 1 |

**Modbus TCP 网关模式:**

| 参数 | 设置值 |
|------|--------|
| 工作模式 | TCP 服务器 |
| 转化协议 | Modbus TCP |
| 端口 | 502 (自动) |
| 波特率 | 9600 |

### 3. 修改配置文件

编辑 `config.yaml`，参考以下多服务器格式：

```yaml
servers:
  - name: 串口服务器1
    connection:
      mode: modbus_tcp          # 或 tcp_transparent
      host: 192.168.1.200
      port: 502
      tcp_timeout: 1
    serial:
      baudrate: 9600
      data_bits: 8
      stop_bits: 1
      parity: none
    devices:
      - slave_addr: 1
        name: 设备1
        device_type: n90sc_counter
        # timeout: 0.5          # 可选，覆盖全局超时
        # retry: 2              # 可选，覆盖全局重试

scheduler:
  interval_seconds: 4           # 采集间隔（秒）
  batch_read: true              # 批量读寄存器
  timeout: 0.3                  # Modbus 读取超时（秒）
  retry: 1                      # Modbus 读取重试次数
  retry_delay: 0.1              # 重试前等待间隔（秒）

database:
  engine: mysql
  host: localhost
  port: 3306
  username: root
  password: yourpassword
  database: yourdatabase
  table_name: plc_data          # 写入表名（可自定义）
```

### 4. 运行

**GUI 模式（推荐）：**

```bash
# 正常模式（连接真实设备）
python monitor_app.py

# 模拟模式（随机测试数据，无需设备）
python monitor_app.py --test

# 指定配置文件
python monitor_app.py -c my_config.yaml

# 开机自启模式（隐藏到托盘，自动开始采集）
python monitor_app.py --auto
```

**命令行模式（无 GUI，仅采集入库）：**

```bash
# 正常采集（写入数据库）
python main.py

# 指定配置文件
python main.py -c my_config.yaml

# 测试模式（仅打印，不写数据库）
python main.py --test
```

**调试快捷脚本：**

```bash
# 自动激活虚拟环境并启动（Windows）
run_debug.bat                  # 正常模式
run_debug.bat --test           # 模拟模式
run_debug.bat -c my_config.yaml
```

## 项目结构

```
plc_collector/
├── monitor_app.py             # GUI 统一启动入口（采集+监控+配置）
├── main.py                    # 命令行采集入口（无 GUI）
├── config.yaml                # 配置文件
├── config_loader.py           # 配置加载与校验
├── run_debug.bat              # 虚拟环境调试启动脚本
├── build_nuitka.bat           # Nuitka 打包脚本（推荐，秒开）
├── build_pyinstaller.bat      # PyInstaller 打包脚本（备选）
├── monitor_app.spec           # PyInstaller 打包配置
├── requirements.txt           # 依赖清单
├── protocol/
│   ├── modbus_rtu.py          # Modbus RTU 帧构造/解析/CRC16
│   ├── device_types.py        # 设备类型注册表（从 DB 加载）
│   └── generic_parser.py      # 通用寄存器解析器
├── transport/
│   ├── base.py                # 传输层抽象基类
│   ├── tcp_transparent.py     # TCP 透传模式
│   └── modbus_tcp.py          # Modbus TCP 网关模式
├── collector/
│   ├── device.py              # 单台设备采集
│   └── scheduler.py           # 多设备轮询调度
├── storage/
│   ├── models.py              # 数据库 ORM 模型
│   ├── db_manager.py          # 数据库管理（连接/写入/清理）
│   └── fault_events.py        # 故障事件持久化
├── gui/
│   ├── monitor/
│   │   ├── main_window.py     # 监控主窗口（工具栏+Tab 页）
│   │   ├── dashboard_tab.py   # 实时数据面板
│   │   └── alarms_tab.py      # 故障告警面板
│   ├── config/
│   │   ├── main_window.py     # 配置对话框（Tab 式）
│   │   ├── servers_page.py    # 服务器配置页
│   │   ├── devices_page.py    # 设备管理页（含范围新增）
│   │   ├── database_page.py   # 数据库配置页
│   │   ├── scheduler_page.py  # 调度配置页
│   │   └── display_page.py    # 展示字段配置页
│   └── shared/
│       ├── async_bridge.py    # asyncio 与 Qt 事件循环桥接
│       └── styles.py          # 全局样式表
├── utils/
│   ├── logger.py              # 日志配置
│   └── paths.py               # 路径工具（兼容开发/PyInstaller/Nuitka）
└── tests/
    └── test_protocol.py       # 单元测试
```

## 打包发布

提供两种打包方式，输出目录互相隔离，互不干扰：

### Nuitka（推荐 — 秒开）

将 Python 代码编译为 C++ 原生二进制，启动无解压延迟：

```bash
build_nuitka.bat
```

- 输出：`dist/PLC_Collector_Nuitka/monitor_app.exe`（单文件 ~32MB）
- 需要 MSVC 14.5+（Visual Studio 2022+）
- 首次编译约 5-10 分钟，增量编译秒级完成

### PyInstaller（备选）

传统打包方式，兼容性好但启动较慢：

```bash
build_pyinstaller.bat
```

- 输出：`dist/PLC_Collector/`（monitor_app.exe + `_internal/` 目录）

两种方式均自动复制 `config.yaml` 到输出目录，整个目录压缩即可分发。

## 技术栈

| 组件 | 技术 |
|------|------|
| 通信协议 | pymodbus（Modbus TCP/RTU） |
| 数据库 ORM | SQLAlchemy 2.0 + PyMySQL |
| GUI 框架 | PySide6 + qasync（asyncio 桥接） |
| 打包工具 | Nuitka（MSVC 14.5）/ PyInstaller |
| 运行平台 | Windows（x86_64） |

## 添加新设备类型（plc-device-import）

本系统通过 **设备类型注册表** 驱动采集，新增设备类型无需修改代码，只需向数据库 `device_type_def` 表写入一条 JSON 定义即可。

项目内置了 `plc-device-import` AI Skill（`plc-device-import.skill`），可在 Qoder 中通过斜杠命令 `/plc-device-import` 调用，自动完成从协议文档到数据库记录的全流程。

### 何时使用

- 接入一台新类型的 Modbus 设备（圆机、计米器、温控器等）
- 拿到设备厂家的协议文档，需要解析寄存器映射
- 需要调整已有设备的寄存器地址或解析规则

### 使用方法

1. 准备好设备的 Modbus 协议文档（PDF / 图片 / 文本均可）
2. 在 Qoder 中输入 `/plc-device-import`，将协议文档提供给 AI
3. Skill 自动完成以下流程：

```
读取协议文档 → 提取寄存器表 → 构建 device_type_def JSON → 验证 → 写入数据库
```

4. 写入后采集程序自动从数据库加载新定义，无需重启

### 定义结构概览

每条设备类型定义包含以下核心部分：

| 字段 | 作用 |
|------|------|
| `device_type` | 唯一标识（如 `n90sc_counter`） |
| `read_mode` | 寄存器读取模式：`contiguous`（连续）或 `grouped`（分组） |
| `registers` | 寄存器地址表（地址、名称、索引） |
| `parse_rules` | 解析规则（direct / combine32 / scale / bitfield / value_map 等 8 种操作） |
| `bit_fields` | 位域批量解析（一个寄存器的各 bit 含义） |
| `run_mode_rules` | 运行模式判断规则 |
| `fault_names` | 故障名称映射 |
| `display_fields` | 仪表板默认展示字段（最多 4 个） |
| `status_map` | 状态颜色/文字映射 |
| `value_mappings` | 枚举值映射表 |

完整的字段说明和两个参考示例（圆机面板 + N90SC 计米器）见 [`plc-device-import/examples.md`](plc-device-import/examples.md)。

## 许可证

[MIT License](LICENSE)
