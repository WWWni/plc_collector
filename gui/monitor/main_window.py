"""采集主窗口
=============
整合实时数据面板、故障告警两个Tab页，以及配置管理对话框。
顶部工具栏含连接状态、开始/停止、配置按钮。
通过Qt Signal安全接收asyncio采集回调数据。
支持多串口服务器架构：管理多个传输层实例。
支持从主界面打开配置对话框，保存后自动重载。
"""

from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QToolBar, QStatusBar, QLabel,
    QPushButton, QWidget, QHBoxLayout, QVBoxLayout, QMessageBox, QApplication,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QAction, QFont
from datetime import datetime
from typing import List, Optional, Callable

from gui.shared.styles import COLORS
from gui.monitor.dashboard_tab import DashboardTab
from gui.monitor.alarms_tab import AlarmsTab


class MonitorMainWindow(QMainWindow):
    """采集主窗口 — 支持多串口服务器及内置配置管理"""

    # Qt信号：用于从asyncio协程安全地传递数据到UI线程
    _data_signal = Signal(list)

    def __init__(self, config, transports=None, db_manager=None,
                 config_path="config.yaml", transport_factory=None, parent=None):
        """
        Args:
            config: AppConfig实例
            transports: 传输层实例列表（按server_index对应config.servers）
            db_manager: 数据库管理器实例
            config_path: 配置文件路径（用于打开配置对话框）
            transport_factory: 传输层工厂函数 callable(config) -> list
        """
        super().__init__(parent)
        self._config = config
        self._transports: list = transports or []
        self._db_manager = db_manager
        self._config_path = config_path
        self._transport_factory = transport_factory
        self._scheduler = None
        self._round_count = 0
        self._cleanup_scheduled = False
        self._collecting = False  # 采集状态标志

        self.setWindowTitle("PLC面板数据采集")
        self.setMinimumSize(1024, 700)
        self.resize(1400, 850)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        # ---- 顶部工具栏 ----
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(toolbar.iconSize())
        self.addToolBar(toolbar)

        # 开始/停止按钮
        self._start_btn = QPushButton("▶ 开始采集")
        self._start_btn.setObjectName("primaryBtn")
        self._start_btn.clicked.connect(self._toggle_collect)
        toolbar.addWidget(self._start_btn)

        # 连接测试按钮
        self._test_btn = QPushButton("↻ 连接测试")
        self._test_btn.setObjectName("secondaryBtn")
        self._test_btn.clicked.connect(self._on_test_connection)
        toolbar.addWidget(self._test_btn)

        toolbar.addSeparator()

        # 配置按钮
        self._config_btn = QPushButton("⚙ 配置")
        self._config_btn.setObjectName("secondaryBtn")
        self._config_btn.clicked.connect(self._on_open_config)
        toolbar.addWidget(self._config_btn)

        toolbar.addSeparator()

        # 连接状态指示灯
        self._conn_label = QLabel("● 未连接")
        self._conn_label.setFixedWidth(180)
        self._conn_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._conn_label.setStyleSheet(
            f"color: {COLORS['status_offline']}; font-weight: bold; "
            f"font-size: 13px; padding: 0 8px;"
        )
        toolbar.addWidget(self._conn_label)

        # 采集轮次
        self._round_label = QLabel("轮次: 0")
        self._round_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; padding: 0 8px;"
        )
        toolbar.addWidget(self._round_label)

        # 弹簧
        spacer = QWidget()
        spacer.setSizePolicy(
            spacer.sizePolicy().horizontalPolicy(), spacer.sizePolicy().verticalPolicy()
        )
        toolbar.addWidget(spacer)

        # 当前时间
        self._time_label = QLabel()
        self._time_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; padding: 0 8px;"
        )
        toolbar.addWidget(self._time_label)

        # 时间刷新定时器
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

        # 数据库清理定时器（每24小时执行一次）
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._periodic_cleanup)
        self._cleanup_timer.start(24 * 3600 * 1000)  # 24小时

        # ---- Tab页（自定义居中Tab栏 + QStackedWidget）----
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # 居中Tab栏
        tab_bar_widget = QWidget()
        tab_bar_widget.setStyleSheet(
            f"background-color: {COLORS['bg_secondary']};"
        )
        tab_bar_layout = QHBoxLayout(tab_bar_widget)
        tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        tab_bar_layout.setSpacing(0)
        tab_bar_layout.addStretch()

        self._tab_btns: list = []
        for text in ["📊 实时数据", "⚠ 故障告警"]:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setFixedHeight(40)
            btn.setMinimumWidth(120)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_secondary']};
                    color: {COLORS['text_secondary']};
                    border: none;
                    border-radius: 0;
                    border-bottom: 2px solid transparent;
                    padding: 8px 20px;
                    font-size: 13px;
                }}
                QPushButton:checked {{
                    color: {COLORS['accent_blue']};
                    border-bottom: 2px solid {COLORS['accent_blue']};
                    font-weight: bold;
                }}
                QPushButton:hover:!checked {{
                    color: {COLORS['text_primary']};
                    border-bottom: 2px solid {COLORS['text_dim']};
                }}
            """)
            idx = len(self._tab_btns)
            btn.clicked.connect(lambda checked, i=idx: self._on_tab_clicked(i))
            tab_bar_layout.addWidget(btn)
            self._tab_btns.append(btn)

        tab_bar_layout.addStretch()
        central_layout.addWidget(tab_bar_widget)

        # 内容区
        self._tabs = QStackedWidget()
        central_layout.addWidget(self._tabs, 1)

        self.setCentralWidget(central)
        self._build_tabs()

        # ---- 状态栏 ----
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        # 多服务器状态汇总
        srv_count = len(self._config.servers)
        total_devices = len(self._config.all_devices)
        srv_details = " | ".join(
            f"{srv.name}({srv.connection.host}:{srv.connection.port})"
            for srv in self._config.servers
        )
        self._status_info = QLabel(
            f"服务器: {srv_count}台 | "
            f"设备: {total_devices}台 | "
            f"间隔: {self._config.scheduler.interval_seconds}s | "
            f"{srv_details}"
        )
        self._statusbar.addWidget(self._status_info)

    def _build_tabs(self):
        """构建/重建Tab页"""
        self._dashboard = DashboardTab(self._config)
        self._tabs.addWidget(self._dashboard)

        self._alarms = AlarmsTab(db_manager=self._db_manager)
        self._tabs.addWidget(self._alarms)

        # 激活第一个tab
        self._on_tab_clicked(0)

    def _on_tab_clicked(self, index: int):
        """切换Tab页"""
        self._tabs.setCurrentIndex(index)
        for i, btn in enumerate(self._tab_btns):
            btn.setChecked(i == index)

    def _rebuild_status_bar(self):
        """重建状态栏信息"""
        srv_count = len(self._config.servers)
        total_devices = len(self._config.all_devices)
        srv_details = " | ".join(
            f"{srv.name}({srv.connection.host}:{srv.connection.port})"
            for srv in self._config.servers
        )
        self._status_info.setText(
            f"服务器: {srv_count}台 | "
            f"设备: {total_devices}台 | "
            f"间隔: {self._config.scheduler.interval_seconds}s | "
            f"{srv_details}"
        )

    def _connect_signals(self):
        """连接信号"""
        self._data_signal.connect(self._on_data_received)

    def _update_clock(self):
        """更新时钟显示"""
        self._time_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _get_device_keys(self) -> list:
        """获取本机所有设备的 (device_name, slave_addr) 标识"""
        return [(dev.name, dev.slave_addr)
                for dev in self._config.all_devices]

    def _startup_cleanup(self):
        """启动时清理过期数据（随机延迟后触发，避免多工控机同时 DELETE）"""
        if self._db_manager:
            try:
                self._db_manager.cleanup_old_data(
                    days=30, device_keys=self._get_device_keys()
                )
            except Exception as e:
                import logging
                logging.getLogger("plc_collector").warning(f"启动清理失败: {e}")

    def _periodic_cleanup(self):
        """定时清理过期数据（每24小时由定时器触发）"""
        if self._db_manager:
            try:
                self._db_manager.cleanup_old_data(
                    days=30, device_keys=self._get_device_keys()
                )
            except Exception as e:
                import logging
                logging.getLogger("plc_collector").warning(f"定期清理失败: {e}")

    # ---- 采集控制 ----

    async def start_collecting(self):
        """启动采集调度（按需创建传输层和数据库，连接并开始采集）"""
        # 按需创建传输层（点击开始时才初始化）
        if not self._transports and self._transport_factory:
            try:
                self._transports = self._transport_factory(self._config)
            except Exception as e:
                QMessageBox.critical(self, "传输层创建失败", str(e))
                return

        if not self._transports:
            self._conn_label.setText("● 无传输层")
            self._conn_label.setStyleSheet(
                f"color: {COLORS['status_offline']}; font-weight: bold; "
                f"font-size: 13px; padding: 0 8px;"
            )
            return

        # 立即切换按钮状态（连接成功/失败都保持此状态，用户可点停止来重置）
        self._collecting = True
        self._start_btn.setText("■ 停止采集")
        self._start_btn.setObjectName("dangerBtn")
        self._start_btn.style().unpolish(self._start_btn)
        self._start_btn.style().polish(self._start_btn)
        self._test_btn.setEnabled(False)

        # 按需初始化数据库（如果启动时未传入db_manager）
        if self._db_manager is None:
            try:
                from storage.db_manager import DatabaseManager
                db_manager = DatabaseManager(self._config.database)
                db_manager.initialize()
                self._db_manager = db_manager
                # 从数据库加载设备类型定义到内存注册表
                from protocol.device_types import (
                    load_from_db as _load_device_types,
                    save_cache as _save_cache,
                )
                n = _load_device_types(db_manager.session_factory)
                if n > 0:
                    import os as _os
                    _config_dir = _os.path.dirname(_os.path.abspath(self._config_path))
                    _save_cache(_config_dir)
                # 数据库就绪后加载历史故障记录
                self._alarms.set_db_manager(self._db_manager)
            except Exception:
                pass  # 数据库不可用时数据不持久化，不影响采集

        # 首次启动时延迟清理过期数据
        if self._db_manager and not self._cleanup_scheduled:
            self._cleanup_scheduled = True
            import random
            delay_ms = random.randint(10, 60) * 1000  # 10~60秒随机延迟
            QTimer.singleShot(delay_ms, self._startup_cleanup)

        try:
            from collector.scheduler import CollectorScheduler

            # 连接所有传输层
            connected = 0
            for idx, transport in enumerate(self._transports):
                srv_name = (
                    self._config.servers[idx].name
                    if idx < len(self._config.servers)
                    else f"服务器{idx}"
                )
                try:
                    if not transport.is_connected:
                        await transport.connect()
                    connected += 1
                except Exception as e:
                    QMessageBox.warning(
                        self, "连接警告",
                        f"服务器 {srv_name} 连接失败: {e}\n"
                        f"该服务器下的设备将无法采集"
                    )

            if connected == 0:
                self._conn_label.setText("● 全部连接失败")
                self._conn_label.setStyleSheet(
                    f"color: {COLORS['status_fault']}; font-weight: bold; "
                    f"font-size: 13px; padding: 0 8px;"
                )
                return

            # 更新连接状态显示
            if connected == len(self._transports):
                self._conn_label.setText(f"● 已连接 ({connected}/{len(self._transports)})")
                self._conn_label.setStyleSheet(
                    f"color: {COLORS['status_running']}; font-weight: bold; "
                    f"font-size: 13px; padding: 0 8px;"
                )
            else:
                self._conn_label.setText(f"● 部分连接 ({connected}/{len(self._transports)})")
                self._conn_label.setStyleSheet(
                    f"color: {COLORS['accent_yellow']}; font-weight: bold; "
                    f"font-size: 13px; padding: 0 8px;"
                )

            self._scheduler = CollectorScheduler(
                config=self._config,
                transports=self._transports,
                on_data=self._on_new_data_async,
            )
            await self._scheduler.start()

        except Exception as e:
            self._conn_label.setText("● 连接失败")
            self._conn_label.setStyleSheet(
                f"color: {COLORS['status_fault']}; font-weight: bold; "
                f"font-size: 13px; padding: 0 8px;"
            )
            QMessageBox.critical(self, "连接失败", str(e))

    async def stop_collecting(self):
        """停止采集"""
        if self._scheduler:
            await self._scheduler.stop()
            self._scheduler = None

        # 断开所有传输层
        for transport in self._transports:
            try:
                await transport.disconnect()
            except Exception:
                pass

        self._conn_label.setText("● 未连接")
        self._conn_label.setStyleSheet(
            f"color: {COLORS['status_offline']}; font-weight: bold; "
            f"font-size: 13px; padding: 0 8px;"
        )
        self._collecting = False
        self._start_btn.setText("▶ 开始采集")
        self._start_btn.setObjectName("primaryBtn")
        self._start_btn.style().unpolish(self._start_btn)
        self._start_btn.style().polish(self._start_btn)
        # 恢复连接测试按钮
        self._test_btn.setEnabled(True)

    def _toggle_collect(self):
        """切换开始/停止采集"""
        import asyncio
        if self._collecting:
            asyncio.ensure_future(self.stop_collecting())
        else:
            asyncio.ensure_future(self.start_collecting())

    def _on_test_connection(self):
        """点击连接测试按钮"""
        import asyncio
        asyncio.ensure_future(self._test_connection())

    async def _test_connection(self):
        """测试所有传输层连通性：连接后立即断开，不启动采集"""
        if not self._transports:
            QMessageBox.warning(self, "连接测试", "无传输层实例（可能处于模拟模式）")
            return

        # 禁用按钮防止重复点击
        self._test_btn.setEnabled(False)
        self._test_btn.setText("↻ 测试中…")
        self._conn_label.setText("● 测试中…")
        self._conn_label.setStyleSheet(
            f"color: {COLORS['accent_yellow']}; font-weight: bold; "
            f"font-size: 13px; padding: 0 8px;"
        )

        results = []
        for idx, transport in enumerate(self._transports):
            srv_name = (
                self._config.servers[idx].name
                if idx < len(self._config.servers)
                else f"服务器{idx}"
            )
            srv_cfg = (
                self._config.servers[idx].connection
                if idx < len(self._config.servers)
                else None
            )
            try:
                await transport.connect()
                await transport.disconnect()
                results.append(f"✓ {srv_name} ({srv_cfg.host}:{srv_cfg.port}) — 连接成功")
            except Exception as e:
                results.append(f"✗ {srv_name} ({srv_cfg.host}:{srv_cfg.port}) — {e}")

        success_count = sum(1 for r in results if r.startswith("✓"))
        all_ok = success_count == len(self._transports)

        if all_ok:
            self._conn_label.setText("● 全部连接正常")
            self._conn_label.setStyleSheet(
                f"color: {COLORS['status_running']}; font-weight: bold; "
                f"font-size: 13px; padding: 0 8px;"
            )
            QMessageBox.information(
                self, "连接测试",
                f"全部 {len(self._transports)} 台服务器连接成功！\n\n"
                + "\n".join(results)
            )
        elif success_count > 0:
            self._conn_label.setText(f"● 部分连接 ({success_count}/{len(self._transports)})")
            self._conn_label.setStyleSheet(
                f"color: {COLORS['accent_yellow']}; font-weight: bold; "
                f"font-size: 13px; padding: 0 8px;"
            )
            QMessageBox.warning(
                self, "连接测试",
                f"{success_count}/{len(self._transports)} 台服务器连接成功\n\n"
                + "\n".join(results)
            )
        else:
            self._conn_label.setText("● 全部连接失败")
            self._conn_label.setStyleSheet(
                f"color: {COLORS['status_fault']}; font-weight: bold; "
                f"font-size: 13px; padding: 0 8px;"
            )
            QMessageBox.critical(
                self, "连接测试",
                "所有服务器连接失败！\n\n" + "\n".join(results)
            )

        self._test_btn.setEnabled(True)
        self._test_btn.setText("↻ 连接测试")

    # ---- 数据回调 ----

    async def _on_new_data_async(self, data_list: list):
        """asyncio采集回调 — 发射Qt信号传递数据"""
        self._data_signal.emit(data_list)

    def _on_data_received(self, data_list: list):
        """Qt信号槽 — 在主线程安全更新UI"""
        self._round_count += 1
        self._round_label.setText(f"轮次: {self._round_count}")

        # 更新各Tab
        self._dashboard.update_devices(data_list)
        self._alarms.check_faults(data_list)

        # 写数据库
        if self._db_manager:
            try:
                self._db_manager.batch_insert(data_list)
            except Exception as e:
                self._statusbar.showMessage(f"数据库写入失败: {e}", 5000)

        # 状态栏提示
        success = len(data_list)
        total = len(self._config.all_devices)
        self._statusbar.showMessage(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"第{self._round_count}轮采集: {success}/{total}台设备成功",
            3000,
        )

    # ---- 模拟数据（测试模式）----

    def start_simulation(self):
        """启动模拟数据（无需真实设备）"""
        self._conn_label.setText("● 模拟模式")
        self._conn_label.setStyleSheet(
            f"color: {COLORS['accent_yellow']}; font-weight: bold; "
            f"font-size: 13px; padding: 0 8px;"
        )
        self._start_btn.setEnabled(False)

        self._sim_timer = QTimer(self)
        self._sim_timer.timeout.connect(lambda: self._generate_sim_data())
        self._sim_timer.start(
            self._config.scheduler.interval_seconds * 1000
        )

    def _generate_sim_data(self):
        """生成模拟数据 — 通用方式，根据设备类型定义自动生成"""
        import random
        from protocol.device_types import get_safe

        data_list = []
        for srv_idx, srv in enumerate(self._config.servers):
            for dev in srv.devices:
                dev_type = getattr(dev, 'device_type', '')
                type_def = get_safe(dev_type)

                if type_def is None:
                    continue

                # 根据读取方式生成随机寄存器值
                if hasattr(type_def, 'READ_GROUPS'):
                    values = {}
                    for i, group in enumerate(type_def.READ_GROUPS):
                        values[f"group_{i}"] = [
                            random.randint(0, 65535) for _ in range(group["count"])
                        ]
                else:
                    values = [
                        random.randint(0, 65535)
                        for _ in range(type_def.REG_COUNT)
                    ]

                data = type_def.parse_registers(values)
                data["run_mode"] = type_def.get_run_mode(data)
                data["active_faults"] = type_def.get_active_faults(data)

                data["timestamp"] = datetime.now()
                data["slave_addr"] = dev.slave_addr
                data["device_name"] = dev.name
                data["device_type"] = dev_type
                data["server_index"] = srv_idx
                data["server_name"] = srv.name
                data_list.append(data)

        self._data_signal.emit(data_list)

    # ---- 配置管理 ----

    def _on_open_config(self):
        """打开配置对话框"""
        import asyncio
        # 正在采集时先停止
        if self._scheduler and self._scheduler.is_running:
            reply = QMessageBox.question(
                self, "配置", "正在采集中，打开配置需要先停止采集，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            asyncio.ensure_future(self._stop_and_open_config())
        else:
            self._do_open_config()

    async def _stop_and_open_config(self):
        """停止采集后打开配置"""
        await self.stop_collecting()
        self._do_open_config()

    def _do_open_config(self):
        """打开配置对话框（模态）"""
        from gui.config.main_window import ConfigMainWindow
        from config_loader import load_config

        dlg = ConfigMainWindow(
            config=self._config,
            config_path=self._config_path,
            parent=self,
        )
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.exec()

        # 对话框关闭后检查是否保存了新配置
        if not getattr(dlg, 'config_saved', False):
            return

        # 重新加载配置
        try:
            new_config = load_config(self._config_path)
        except Exception as e:
            QMessageBox.critical(self, "配置重载失败", f"无法重新加载配置文件:\n{e}")
            return

        # 停止采集（如有）
        import asyncio
        if self._scheduler and self._scheduler.is_running:
            asyncio.ensure_future(self._stop_and_reload(new_config))
        else:
            asyncio.ensure_future(self._apply_new_config(new_config))

    async def _stop_and_reload(self, new_config):
        """停止采集后重载配置"""
        await self.stop_collecting()
        await self._apply_new_config(new_config)

    async def _apply_new_config(self, new_config):
        """应用新配置：重建传输层和UI"""
        self._config = new_config

        # 清理旧传输层
        for t in self._transports:
            try:
                await t.disconnect()
            except Exception:
                pass

        # 重建传输层
        if self._transport_factory:
            try:
                self._transports = self._transport_factory(self._config)
            except Exception as e:
                QMessageBox.warning(
                    self, "传输层创建失败",
                    f"无法创建传输层，将使用模拟模式:\n{e}"
                )
                self._transports = []

        # 重建Tab页
        while self._tabs.count():
            w = self._tabs.widget(0)
            self._tabs.removeWidget(w)
        self._build_tabs()

        # 更新状态栏
        self._rebuild_status_bar()

        # 重置轮次计数
        self._round_count = 0
        self._round_label.setText("轮次: 0")

        # 恢复连接状态
        self._conn_label.setText("● 未连接")
        self._conn_label.setStyleSheet(
            f"color: {COLORS['status_offline']}; font-weight: bold; "
            f"font-size: 13px; padding: 0 8px;"
        )
        self._collecting = False
        self._start_btn.setText("▶ 开始采集")
        self._start_btn.setObjectName("primaryBtn")
        self._start_btn.style().unpolish(self._start_btn)
        self._start_btn.style().polish(self._start_btn)
        self._test_btn.setEnabled(True)

        self._statusbar.showMessage("配置已重载", 5000)

    def closeEvent(self, event):
        """窗口关闭时清理"""
        import asyncio
        if self._scheduler:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.stop_collecting())
            except Exception:
                pass
        event.accept()
