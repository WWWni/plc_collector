# PLC面板数据采集系统

基于ZLAN5143D串口服务器的工业面板数据采集系统，支持TCP透传和Modbus TCP两种通信模式，提供GUI监控界面和命令行两种运行方式。

## 系统架构

```
面板设备(RS485) ──RS485──> ZLAN5143D ──Ethernet──> 采集程序(Python) ──> MySQL/PostgreSQL
                                                       │
                                                       ├── monitor_app.py  (GUI监控+配置)
                                                       └── main.py         (命令行采集)
```

**核心特性：**
- 多串口服务器架构：每台ZLAN5143D独立传输层，互不影响
- 设备类型注册表：从数据库动态加载设备类型定义，支持多种设备混采
- GUI监控界面：实时数据面板 + 故障告警 + 内置配置管理，单实例运行
- 多工控机数据隔离：通过 `collector_id` 自动隔离不同工控机的数据

## 快速开始

### 1. 安装依赖

```bash
# 推荐使用虚拟环境
python -m venv my_env
my_env\Scripts\activate

pip install -r requirements.txt
```

### 2. 配置ZLAN5143D

使用ZLVircom工具配置串口服务器参数：

**TCP透传模式 (推荐):**
| 参数 | 设置值 |
|------|--------|
| 工作模式 | TCP服务器 |
| 转化协议 | NONE |
| 端口 | 4196 |
| 波特率 | 9600 |
| 数据位 | 8 |
| 校验位 | 无 |
| 停止位 | 1 |

**Modbus TCP网关模式:**
| 参数 | 设置值 |
|------|--------|
| 工作模式 | TCP服务器 |
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

scheduler:
  interval_seconds: 4           # 采集间隔（秒）
  batch_read: true              # 批量读寄存器
  timeout: 0.3                  # Modbus读取超时（秒）
  retry: 1                      # Modbus读取重试次数
  retry_delay: 0.1              # 重试前等待间隔（秒）

database:
  engine: mysql
  host: 192.168.0.33
  port: 3306
  username: root
  password: '123456'
  database: oldmes
  table_name: plc_data          # 写入表名（可自定义）
```

### 4. 运行

**GUI模式（推荐）：**
```bash
# 正常模式（连接真实设备）
python monitor_app.py

# 模拟模式（随机测试数据，无需设备）
python monitor_app.py --test

# 指定配置文件
python monitor_app.py -c my_config.yaml
```

**命令行模式（无GUI，仅采集入库）：**
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
├── monitor_app.py             # GUI统一启动入口（采集+监控+配置）
├── main.py                    # 命令行采集入口（无GUI）
├── config.yaml                # 配置文件
├── config_loader.py           # 配置加载与校验
├── run_debug.bat              # 虚拟环境调试启动脚本
├── build.bat                  # PyInstaller打包脚本
├── requirements.txt           # 依赖清单
├── protocol/
│   ├── modbus_rtu.py          # Modbus RTU帧构造/解析/CRC16
│   ├── device_types.py        # 设备类型注册表（从DB加载）
│   └── generic_parser.py      # 通用寄存器解析器
├── transport/
│   ├── base.py                # 传输层抽象基类
│   ├── tcp_transparent.py     # TCP透传模式
│   └── modbus_tcp.py          # Modbus TCP网关模式
├── collector/
│   ├── device.py              # 单台设备采集
│   └── scheduler.py           # 多设备轮询调度
├── storage/
│   ├── models.py              # 数据库ORM模型
│   ├── db_manager.py          # 数据库管理（连接/写入/清理）
│   └── fault_events.py        # 故障事件持久化
├── gui/
│   ├── monitor/
│   │   ├── main_window.py     # 监控主窗口（工具栏+Tab页）
│   │   ├── dashboard_tab.py   # 实时数据面板
│   │   └── alarms_tab.py      # 故障告警面板
│   ├── config/
│   │   ├── main_window.py     # 配置对话框（Tab式）
│   │   ├── servers_page.py    # 服务器配置页
│   │   ├── devices_page.py    # 设备管理页（含范围新增）
│   │   ├── database_page.py   # 数据库配置页
│   │   ├── scheduler_page.py  # 调度配置页
│   │   └── display_page.py    # 展示字段配置页
│   └── shared/
│       ├── async_bridge.py    # asyncio与Qt事件循环桥接
│       └── styles.py          # 全局样式表
├── utils/
│   ├── logger.py              # 日志配置
│   └── paths.py               # 路径工具（兼容开发/打包）
└── tests/
    └── test_protocol.py       # 单元测试
```

## 打包发布

```bash
build.bat
```

打包输出在 `dist/PLC_Collector/` 目录，内含 `monitor_app.exe` + `config.yaml` + `_internal/`，整个目录压缩即可分发。

