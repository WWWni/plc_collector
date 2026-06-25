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
    QSystemTrayIcon, QMenu,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QAction, QFont, QIcon
import sys
from datetime import datetime
from typing import List, Optional, Callable

from gui.shared.styles import COLORS
from gui.monitor.dashboard_tab import DashboardTab
from gui.monitor.alarms_tab import AlarmsTab


class MonitorMainWindow(QMainWindow):
    """采集主窗口 — 支持多串口服务器及内置配置管理"""

    # Qt信号：用于从asyncio协程安全地传递数据到UI线程
    _data_signal = Signal(list)
    # 后台初始化完成信号（线程安全）
    _init_done_signal = Signal()
    # 单实例恢复信号（从后台 Win32 监听线程触发）
    _restore_signal = Signal()

    def __init__(self, config, transports=None, db_manager=None,
                 config_path="config.yaml", config_dir="", transport_factory=None,
                 auto_start=False, parent=None):
        """
        Args:
            config: AppConfig实例
            transports: 传输层实例列表（按server_index对应config.servers）
            db_manager: 数据库管理器实例
            config_path: 配置文件路径（用于打开配置对话框）
            config_dir: 配置文件所在目录（用于缓存文件定位）
            transport_factory: 传输层工厂函数 callable(config) -> list
            auto_start: 开机自启模式，初始化完成后自动开始采集
        """
        super().__init__(parent)
        self._config = config
        self._transports: list = transports or []
        self._db_manager = db_manager
        self._config_path = config_path
        self._config_dir = config_dir
        self._transport_factory = transport_factory
        self._auto_start = auto_start
        self._scheduler = None
        self._round_count = 0
        self._cleanup_scheduled = False
        self._collecting = False  # 采集状态标志
        self._really_close = False  # 真正退出标志

        self.setWindowTitle("PLC面板数据采集")
        self.setMinimumSize(900, 650)
        self.resize(1000, 680)

        self._setup_ui()
        self._connect_signals()
        self._setup_tray()

        # 单实例恢复：启动后台 Win32 监听窗口（不受 Qt hide() 影响）
        if sys.platform == "win32":
            self._restore_signal.connect(self._tray_restore)
            self._start_restore_listener()

        # 初始化期间禁用操作按钮
        self._start_btn.setEnabled(False)
        self._test_btn.setEnabled(False)
        self._config_btn.setEnabled(False)
        self._conn_label.setText("● 正在初始化...")
        self._conn_label.setStyleSheet(
            f"color: {COLORS['accent_yellow']}; font-weight: bold; "
            f"font-size: 13px; padding: 0 8px;"
        )

        # 界面显示后延迟触发后台初始化
        QTimer.singleShot(100, self._on_init_ready)

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
        self._init_done_signal.connect(self._on_init_done)

    def _setup_tray(self):
        """设置系统托盘图标"""
        import os
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "favicon.ico")
        app_icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.setWindowIcon(app_icon)

        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(app_icon)
        self._tray_icon.setToolTip("PLC面板数据采集")

        # 托盘右键菜单
        tray_menu = QMenu()
        tray_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLORS['bg_secondary']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
            }}
            QMenu::item:selected {{
                background-color: {COLORS['accent_blue']};
            }}
            QMenu::separator {{
                height: 1px;
                background: {COLORS['border']};
                margin: 4px 8px;
            }}
        """)
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self._tray_restore)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._tray_quit)
        tray_menu.addAction(quit_action)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _on_tray_activated(self, reason):
        """托盘图标双击时恢复窗口"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_restore()

    def _tray_restore(self):
        """从托盘或任务栏恢复窗口到前台"""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        if sys.platform == "win32":
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(self.winId())
            # AttachThreadInput 绕过 Windows 前台窗口限制：
            # 将当前线程挂接到当前拥有焦点的线程，临时获取 SetForegroundWindow 权限
            fore_hwnd = user32.GetForegroundWindow()
            fore_tid = user32.GetWindowThreadProcessId(fore_hwnd, None)
            cur_tid = kernel32.GetCurrentThreadId()
            if fore_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fore_tid, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if fore_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fore_tid, False)

    def _start_restore_listener(self):
        """启动后台 Win32 窗口监听单实例恢复消息

        Qt hide() 后 nativeEvent 不再接收消息，因此创建一个独立的
        Win32 隐藏窗口在后台线程运行消息循环，收到恢复消息后通过 Qt Signal
        安全地通知主线程恢复窗口。
        """
        import ctypes
        import ctypes.wintypes
        import threading

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.wintypes.HWND, ctypes.c_uint,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
        )

        wm_restore = ctypes.windll.user32.RegisterWindowMessageW(
            "PLC_Collector_RestoreWindow"
        )
        signal = self._restore_signal  # 捕获到闭包

        @WNDPROC
        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == wm_restore:
                signal.emit()
                return 0
            return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        # 防止回调被 GC 回收
        self._wnd_proc_ref = _wnd_proc

        def _listener_thread():
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", ctypes.c_uint),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", ctypes.wintypes.HINSTANCE),
                    ("hIcon", ctypes.wintypes.HICON),
                    ("hCursor", ctypes.wintypes.HANDLE),
                    ("hbrBackground", ctypes.wintypes.HBRUSH),
                    ("lpszMenuName", ctypes.wintypes.LPCWSTR),
                    ("lpszClassName", ctypes.wintypes.LPCWSTR),
                ]

            hinstance = kernel32.GetModuleHandleW(None)
            class_name = "PLC_Collector_Listener"

            wc = WNDCLASSW()
            wc.lpfnWndProc = _wnd_proc
            wc.hInstance = hinstance
            wc.lpszClassName = class_name
            user32.RegisterClassW(ctypes.byref(wc))

            hwnd = user32.CreateWindowExW(
                0, class_name, "PLC Listener",
                0, 0, 0, 0, 0,
                None, None, hinstance, None,
            )

            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        t = threading.Thread(target=_listener_thread, daemon=True)
        t.start()

    def _tray_quit(self):
        """真正退出程序"""
        self._really_close = True
        self._tray_icon.hide()
        self.close()
        QApplication.quit()

    def nativeEvent(self, eventType, message):
        """拦截 WM_CLOSE 消息：点 X 时转为最小化到托盘，Qt 不会收到 closeEvent"""
        if eventType == b"windows_generic_MSG":
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(message.__int__())
            if msg.message == 0x0010:  # WM_CLOSE
                if self._really_close:
                    return super().nativeEvent(eventType, message)
                else:
                    # 标记本次最小化需要隐藏到托盘
                    self._minimize_to_tray = True
                    self.showMinimized()
                    return True, 0
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event):
        """仅在 _tray_quit 调用 self.close() 时触发（真正退出）"""
        if self._really_close:
            self._tray_icon.hide()
            event.accept()
        else:
            event.ignore()

    def changeEvent(self, event):
        """监听窗口状态变化"""
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                # 只有从 X 按钮触发的最小化才隐藏到托盘
                if getattr(self, '_minimize_to_tray', False):
                    self._minimize_to_tray = False
                    QTimer.singleShot(200, self._hide_to_tray)

    def _hide_to_tray(self):
        """隐藏窗口到系统托盘"""
        self.hide()
        self._tray_icon.showMessage(
            "PLC面板数据采集",
            "程序已最小化到系统托盘，双击托盘图标可恢复窗口。",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def _on_init_ready(self):
        """界面显示后启动后台线程做数据库初始化"""
        import threading
        t = threading.Thread(target=self._do_bg_init, daemon=True)
        t.start()
        # 安全兜底：60 秒后如果初始化还没完成，强制启用按钮
        QTimer.singleShot(60000, self._on_init_done)

    def _do_bg_init(self):
        """后台线程：数据库连接 + 设备类型加载"""
        import logging
        logger = logging.getLogger("plc_collector.app")
        logger.info(f"[bg_init] collector_id={self._config.collector_id!r}")

        try:
            from storage.db_manager import DatabaseManager
            from protocol.device_types import (
                load_from_db as load_device_types_from_db,
                save_cache,
            )
            self._db_manager = DatabaseManager(
                self._config.database, collector_id=self._config.collector_id
            )
            self._db_manager.initialize()
            n = load_device_types_from_db(self._db_manager.session_factory)
            if n > 0:
                save_cache(self._config_dir)
            logger.info(f"数据库初始化成功，从DB加载 {n} 个设备类型定义（缓存已更新）")
        except Exception as e:
            logger.warning(f"数据库初始化失败，继续使用缓存中的设备类型定义: {e}")
            self._db_manager = None

        # 通过信号通知主线程更新 UI（线程安全）
        logger.info("[init_done] 后台初始化完成，发送信号")
        self._init_done_signal.emit()

    def _on_init_done(self):
        """后台初始化完成，在主线程中启用按钮（可被多次调用，幂等）"""
        import logging
        import time
        _logger = logging.getLogger("plc_collector.app")
        _t0 = time.monotonic()

        if self._start_btn.isEnabled():
            return  # 已经启用过，跳过

        _logger.info(f"[init_done] 信号到达主线程")

        self._start_btn.setEnabled(True)
        self._test_btn.setEnabled(True)
        self._config_btn.setEnabled(True)
        self._conn_label.setText("● 未连接")
        self._conn_label.setStyleSheet(
            f"color: {COLORS['status_offline']}; font-weight: bold; "
            f"font-size: 13px; padding: 0 8px;"
        )

        # 刷新卡片的type_def，让离线状态立即显示正确的中文和颜色
        if hasattr(self, '_dashboard'):
            self._dashboard.refresh_type_defs()
            _logger.info(f"[init_done] refresh_type_defs 完成 +{time.monotonic()-_t0:.3f}s")

        # 将 db_manager 传给告警页，后台线程加载历史告警数据（不阻塞 UI）
        if self._db_manager and hasattr(self, '_alarms'):
            self._alarms.set_db_manager(self._db_manager)
            self._alarms.load_from_db_async()
            _logger.info(f"[init_done] alarms 后台加载已启动 +{time.monotonic()-_t0:.3f}s")

        # 开机自启模式：初始化完成后自动开始采集
        if self._auto_start:
            import asyncio
            asyncio.ensure_future(self.start_collecting())

        _logger.info(f"[init_done] 全部完成 +{time.monotonic()-_t0:.3f}s")

    def _update_clock(self):
        """更新时钟显示"""
        self._time_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _get_device_keys(self) -> list:
        """获取本机所有设备的 (device_name, slave_addr) 标识"""
        return [(dev.name, dev.slave_addr)
                for dev in self._config.all_devices]

    def _startup_cleanup(self):
        """启动时清理过期分区（随机延迟后触发，避免多工控机同时操作）"""
        if self._db_manager:
            try:
                self._db_manager.cleanup_old_data(days=30)
            except Exception as e:
                import logging
                logging.getLogger("plc_collector").warning(f"启动清理失败: {e}")

    def _periodic_cleanup(self):
        """定时清理过期数据（每24小时由定时器触发）"""
        if self._db_manager:
            try:
                self._db_manager.cleanup_old_data(days=30)
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
                db_manager = DatabaseManager(self._config.database, collector_id=self._config.collector_id)
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
                self._collecting = False  # 标记启动失败，_do_start 会恢复按钮
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
            self._collecting = False  # 标记启动失败，_do_start 会恢复按钮
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

    def _set_btn_start(self):
        """将按钮恢复为'开始采集'就绪状态"""
        self._collecting = False
        self._start_btn.setEnabled(True)
        self._start_btn.setText("▶ 开始采集")
        self._start_btn.setObjectName("primaryBtn")
        self._start_btn.style().unpolish(self._start_btn)
        self._start_btn.style().polish(self._start_btn)

    def _toggle_collect(self):
        """切换开始/停止采集（点击后立即禁用按钮，异步完成后恢复）"""
        import asyncio

        if self._collecting:
            # 立即显示 loading 状态，防止重复点击
            self._start_btn.setEnabled(False)
            self._start_btn.setText("⏳ 正在停止…")
            self._start_btn.setObjectName("secondaryBtn")
            self._start_btn.style().unpolish(self._start_btn)
            self._start_btn.style().polish(self._start_btn)
            asyncio.ensure_future(self._do_stop())
        else:
            # 立即显示 loading 状态
            self._start_btn.setEnabled(False)
            self._start_btn.setText("⏳ 正在启动…")
            self._start_btn.setObjectName("secondaryBtn")
            self._start_btn.style().unpolish(self._start_btn)
            self._start_btn.style().polish(self._start_btn)
            asyncio.ensure_future(self._do_start())

    async def _do_stop(self):
        """异步停止采集，完成后恢复按钮为'开始采集'"""
        try:
            await self.stop_collecting()
        finally:
            # stop_collecting 已重置 _collecting=False 和按钮文本，这里只需确保按钮可用
            self._start_btn.setEnabled(True)

    async def _do_start(self):
        """异步启动采集，若失败则恢复按钮为'开始采集'"""
        try:
            await self.start_collecting()
        finally:
            # 若启动失败（_collecting 仍为 False），恢复为开始状态
            if not self._collecting:
                self._set_btn_start()
            else:
                # 启动成功，确保按钮可用（stop_collecting 内部已设置文本和样式）
                self._start_btn.setEnabled(True)

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
        """打开配置对话框（无论是否在采集都可以打开查看）"""
        self._do_open_config()

    def _do_open_config(self):
        """打开配置对话框（模态）"""
        from gui.config.main_window import ConfigMainWindow
        from config_loader import load_config

        # 记录打开配置时是否在采集
        was_collecting = self._collecting and self._scheduler and self._scheduler.is_running

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

        # 采集中保存配置 → 提示用户将重启采集
        auto_restart = False
        if was_collecting:
            reply = QMessageBox.question(
                self, "配置已修改",
                "配置已保存，修改配置需要重启采集。\n是否立即重启？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            auto_restart = (reply == QMessageBox.StandardButton.Yes)

        # 重新加载配置（无论是否重启采集都要加载）
        try:
            new_config = load_config(self._config_path)
        except Exception as e:
            QMessageBox.critical(self, "配置重载失败", f"无法重新加载配置文件:\n{e}")
            return

        # 应用新配置
        import asyncio
        if was_collecting:
            asyncio.ensure_future(self._reload_with_loading(new_config, auto_restart))
        else:
            asyncio.ensure_future(self._apply_new_config(new_config))

    def _set_loading_state(self, loading: bool):
        """设置加载过渡状态：禁用/启用所有操作按钮"""
        self._start_btn.setEnabled(not loading)
        self._test_btn.setEnabled(not loading)
        self._config_btn.setEnabled(not loading)
        if loading:
            self._start_btn.setText("⏳ 配置重载中...")
            self._conn_label.setText("● 配置重载中...")
            self._conn_label.setStyleSheet(
                f"color: {COLORS['accent_yellow']}; font-weight: bold; "
                f"font-size: 13px; padding: 0 8px;"
            )

    async def _reload_with_loading(self, new_config, auto_restart: bool):
        """停止 → 应用配置 → 可选重启采集，全程显示加载状态"""
        self._set_loading_state(True)
        try:
            await self.stop_collecting()
            await self._apply_new_config(new_config)
            if auto_restart:
                await self.start_collecting()
        finally:
            self._set_loading_state(False)

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
