# AGENTS.md — AI Agent 项目指南

本文件为 AI 编码助手提供项目上下文，修改代码前请务必阅读。

## 项目概述

PLC 面板数据采集系统：通过 ZLAN5143D 串口服务器，采集工业面板设备（Modbus RTU/TCP）的运行数据并写入 MySQL。

- **运行平台**: Windows x86_64
- **Python**: 3.14（虚拟环境 `my_env/`）
- **入口**: `monitor_app.py`（GUI）/ `main.py`（CLI）

## 技术栈

| 组件 | 库 |
|------|------|
| 通信协议 | pymodbus >= 3.5（Modbus TCP/RTU） |
| 数据库 ORM | SQLAlchemy 2.0 + PyMySQL |
| GUI 框架 | PySide6 + qasync（asyncio↔Qt 桥接） |
| 实时图表 | pyqtgraph |
| 配置解析 | PyYAML |
| 打包工具 | Nuitka（推荐）/ PyInstaller |

## 架构分层

```
monitor_app.py / main.py          # 启动入口
├── config_loader.py              # 配置加载（dataclass 模型）
├── transport/                    # 传输层（TCP透传 / Modbus TCP）
├── collector/                    # 采集层（设备轮询调度）
├── protocol/                     # 协议层（Modbus RTU帧 / 设备类型注册表 / 通用解析器）
├── storage/                      # 存储层（ORM模型 / DB管理 / 故障事件）
├── gui/                          # GUI层
│   ├── monitor/                  #   监控主窗口 + 仪表板 + 告警
│   ├── config/                   #   配置对话框（Tab式）
│   └── shared/                   #   async桥接 + 全局样式
└── utils/                        # 工具（日志 / 路径兼容）
```

**关键原则**: GUI 与业务逻辑通过 Qt Signal 解耦，数据库和传输层按需延迟初始化（用户点击"开始采集"后才连接）。

## 核心约定

### 术语

- UI 和代码中统一使用 **"设备"**（不使用"织机"）
- 连接模式：`modbus_tcp`（默认）/ `tcp_transparent`
- 设备唯一标识：`设备名 + 从站地址` 组合

### 配置优先级

```
per-device 参数 > 服务器全局参数 > 代码默认值
```

`config.yaml` 中 `devices` 列表的 `timeout`/`retry` 字段为 `None` 时自动回退到所属服务器的全局值。所有扩展必须向后兼容。

### 代码规范

- **修改前必须重新读取文件**：用户会同时修改代码，助手上下文中的代码可能已过时
- **数据库字段注释**：ORM 模型的 Column 使用中文 `comment=` 参数，同步到 MySQL 字段 COMMENT
- **docstring 插入**：使用 SearchReplace 插入三引号 docstring 前，检查是否与已有三引号冲突
- **pymodbus 兼容性**：从站地址参数名需动态检测（`slave` / `unit` / `device_id`，不同版本不同），使用签名内省而非版本号判断

### 数据库

- 写入表名可通过 `config.yaml` 的 `database.table_name` 配置
- `SQLAlchemy create_all` 不会自动补充缺失列，需手动 `ALTER TABLE`
- 多工控机共享数据库时，通过 `collector_id` 隔离数据
- 历史数据按天分区（RANGE PARTITION），保留 30 天，清理通过 `DROP PARTITION` 瞬间完成

### GUI

- 窗口最小尺寸 900×650，目标分辨率 1024×768
- 仪表板卡片最多展示 4 个字段
- 单实例运行：Win32 独立监听窗口 + PostMessage 跨进程通信 + AttachThreadInput 前置
- 托盘隐藏后点 X 不退出，`app.setQuitOnLastWindowClosed(False)`

### Windows 构建脚本

- 所有 `.bat` 脚本开头必须 `chcp 936 >nul`（中文路径兼容）
- 路径使用 `%~dp0` 而非硬编码，避免中文路径问题
- Nuitka 输出 `dist/PLC_Collector_Nuitka/`，PyInstaller 输出 `dist/PLC_Collector/`，互不干扰

## 添加新设备类型

无需修改代码。使用 `/plc-device-import` Skill 将设备协议文档转换为 `device_type_def` 表记录即可。详见 `plc-device-import/SKILL.md`。

## 运行与测试

```bash
# 激活虚拟环境
my_env\Scripts\activate

# GUI 模式
python monitor_app.py              # 正常模式
python monitor_app.py --test       # 模拟模式（随机数据）
python monitor_app.py --auto       # 开机自启（隐藏到托盘+自动采集）

# CLI 模式
python main.py                     # 正常采集
python main.py --test              # 仅打印不写库

# 打包
build_nuitka.bat                   # Nuitka（推荐，秒开）
build_pyinstaller.bat              # PyInstaller（备选）
```

## 禁止事项

- **不要**在 GUI 初始化阶段执行阻塞操作（数据库连接、网络请求），必须在用户操作后延迟触发
- **不要**硬编码从站地址参数名（`slave`/`unit`/`device_id`），使用 `transport/base.py` 中的动态检测
- **不要**在 `for range(retry)` 中从 0 开始（`retry=0` 时完全不执行），使用 `range(1, retry + 1)`
- **不要**在 Windows bat 脚本中使用 `chcp 65001`（UTF-8），中文路径下文件操作不可靠，统一用 `chcp 936`
- **不要**创建 `README` 或其他文档文件，除非用户明确要求
