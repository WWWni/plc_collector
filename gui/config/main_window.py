"""配置对话框
====================
左侧导航栏切换配置页，右侧内容区显示对应表单。
底部按钮栏: 保存 / 重新加载 / 测试连接。

支持多串口服务器架构，由主程序以模态对话框方式打开。
"""

import os
import yaml
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QLabel, QMessageBox, QFrame,
    QSizePolicy, QApplication,
)
from PySide6.QtCore import Qt, QSize

from gui.shared.styles import COLORS
from gui.config.servers_page import ServersPage
from gui.config.devices_page import DevicesPage
from gui.config.database_page import DatabasePage
from gui.config.scheduler_page import SchedulerPage
from gui.config.display_page import DisplayPage
from gui.config.statistics_page import StatisticsPage


class NavButton(QPushButton):
    """左侧导航按钮"""

    def __init__(self, text, icon_text="", parent=None):
        super().__init__(parent)
        self.setText(f"  {icon_text}  {text}")
        self.setCheckable(True)
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding-left: 16px;
                background-color: transparent;
                color: {COLORS['text_secondary']};
                border: none;
                border-left: 3px solid transparent;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_primary']};
            }}
            QPushButton:checked {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['accent_blue']};
                border-left: 3px solid {COLORS['accent_blue']};
                font-weight: bold;
            }}
        """)


class ConfigMainWindow(QDialog):
    """配置对话框主窗口（由采集主程序以模态方式打开）"""

    def __init__(self, config, config_path="config.yaml", parent=None):
        super().__init__(parent)
        self._config = config
        self._config_path = config_path
        self.config_saved = False  # 外部读取此标志判断是否保存了新配置

        self.setWindowTitle("PLC数据采集 — 配置管理")
        self.setMinimumSize(900, 650)
        self.resize(1000, 680)

        self._setup_ui()

    def _setup_ui(self):
        # 外层垂直布局：内容区 + 状态栏
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ---- 主内容区（导航 + 右侧）----
        content_widget = QWidget()
        main_layout = QHBoxLayout(content_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- 左侧导航栏 ----
        nav_frame = QFrame()
        nav_frame.setFixedWidth(200)
        nav_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_secondary']};
                border-right: 1px solid {COLORS['border']};
            }}
        """)
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(0, 16, 0, 16)
        nav_layout.setSpacing(4)

        # 标题
        title_label = QLabel("  配置管理")
        title_label.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {COLORS['accent_blue']}; "
            f"padding: 8px 16px 16px 16px;"
        )
        nav_layout.addWidget(title_label)

        # 导航按钮
        self._nav_buttons = []

        nav_items = [
            ("服务器管理", "🔗"),
            ("设备管理", "📟"),
            ("采集参数", "⏱"),
            ("数据库", "💾"),
            ("展示配置", "📊"),
            ("统计配置", "📈"),
        ]

        for text, icon in nav_items:
            btn = NavButton(text, icon)
            btn.clicked.connect(lambda checked, b=btn: self._on_nav_clicked(b))
            nav_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        nav_layout.addStretch()

        # 配置文件路径
        path_label = QLabel(f"  {os.path.basename(self._config_path)}")
        path_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; "
            f"padding: 8px 16px;"
        )
        path_label.setWordWrap(True)
        nav_layout.addWidget(path_label)

        main_layout.addWidget(nav_frame)

        # ---- 右侧内容区 ----
        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(0, 0, 0, 0)
        right_panel.setSpacing(0)

        # 页面堆栈
        self._stack = QStackedWidget()

        self._servers_page = ServersPage(self._config)
        self._devices_page = DevicesPage(self._config)
        self._scheduler_page = SchedulerPage(self._config)
        self._database_page = DatabasePage(self._config)
        self._display_page = DisplayPage(self._config)
        self._statistics_page = StatisticsPage(self._config)

        self._stack.addWidget(self._servers_page)
        self._stack.addWidget(self._devices_page)
        self._stack.addWidget(self._scheduler_page)
        self._stack.addWidget(self._database_page)
        self._stack.addWidget(self._display_page)
        self._stack.addWidget(self._statistics_page)

        right_panel.addWidget(self._stack, 1)

        # ---- 底部按钮栏 ----
        bottom_bar = QFrame()
        bottom_bar.setFixedHeight(64)
        bottom_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_secondary']};
                border-top: 1px solid {COLORS['border']};
            }}
        """)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(24, 12, 24, 12)

        reload_btn = QPushButton("重新加载")
        reload_btn.clicked.connect(self._reload_config)
        bottom_layout.addWidget(reload_btn)

        bottom_layout.addStretch()

        save_btn = QPushButton("保存配置")
        save_btn.setObjectName("primaryBtn")
        save_btn.setMinimumWidth(120)
        save_btn.clicked.connect(self._save_config)
        bottom_layout.addWidget(save_btn)

        bottom_layout.addSpacing(12)

        close_btn = QPushButton("关闭")
        close_btn.setMinimumWidth(80)
        close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(close_btn)

        right_panel.addWidget(bottom_bar)

        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        main_layout.addWidget(right_widget, 1)

        outer_layout.addWidget(content_widget, 1)

        # ---- 状态栏（用 QLabel 代替 QStatusBar）----
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; padding: 4px 16px; "
            f"border-top: 1px solid {COLORS['border']};"
        )
        self._status_label.setFixedHeight(28)
        outer_layout.addWidget(self._status_label)

        # 默认选中第一个
        if self._nav_buttons:
            self._nav_buttons[0].setChecked(True)

    def _on_nav_clicked(self, clicked_btn):
        """导航按钮点击"""
        for i, btn in enumerate(self._nav_buttons):
            if btn == clicked_btn:
                btn.setChecked(True)
                self._stack.setCurrentIndex(i)
                # 切换到设备管理页时，同步服务器名称
                if i == 1:
                    names = self._servers_page.get_server_names()
                    self._devices_page.update_server_names(names)
            else:
                btn.setChecked(False)

    def _show_status(self, message: str):
        """显示状态消息"""
        self._status_label.setText(message)

    def _collect_all(self) -> dict:
        """
        收集所有页面配置，合并为完整配置字典。
        servers_page 提供连接/串口参数，devices_page 提供设备列表。
        """
        servers_data = self._servers_page.save_to_dict()  # {"servers": [...]}
        devices_data = self._devices_page.save_to_dict()  # {"_servers_devices": [...]}
        sched_data = self._scheduler_page.save_to_dict()
        db_data = self._database_page.save_to_dict()
        display_data = self._display_page.save_to_dict()  # {"display_config": {...}}
        stats_data = self._statistics_page.save_to_dict()  # {"statistics_config": {...}}

        # 将设备列表合并到对应的服务器配置中
        servers_list = servers_data.get("servers", [])
        servers_devices = devices_data.get("_servers_devices", [])

        for idx, srv in enumerate(servers_list):
            if idx < len(servers_devices):
                srv["devices"] = servers_devices[idx]
            else:
                srv["devices"] = []

        merged = {"servers": servers_list}
        merged.update(sched_data)
        merged.update(db_data)
        merged.update(display_data)
        merged.update(stats_data)
        return merged

    def _validate_all(self) -> list:
        """校验所有页面"""
        errors = []
        for page in [
            self._servers_page,
            self._devices_page,
            self._scheduler_page,
            self._database_page,
            self._display_page,
            self._statistics_page,
        ]:
            errors.extend(page.validate())
        return errors

    def _save_config(self):
        """保存配置到YAML"""
        # 先同步服务器名称到设备页
        names = self._servers_page.get_server_names()
        self._devices_page.update_server_names(names)

        # 校验
        errors = self._validate_all()
        if errors:
            msg = "配置校验失败:\n\n" + "\n".join(f"  - {e}" for e in errors)
            QMessageBox.warning(self, "校验失败", msg)
            return

        config_dict = self._collect_all()

        try:
            # 备份原文件
            if os.path.exists(self._config_path):
                backup_path = self._config_path + ".bak"
                with open(self._config_path, "r", encoding="utf-8") as f:
                    backup_content = f.read()
                with open(backup_path, "w", encoding="utf-8") as f:
                    f.write(backup_content)

            # 写入YAML（带中文注释头）
            yaml_header = (
                "# PLC面板数据采集系统 - 配置文件\n"
                "# 由采集程序配置界面自动生成\n"
                "# ================================\n\n"
            )

            with open(self._config_path, "w", encoding="utf-8") as f:
                f.write(yaml_header)
                yaml.dump(
                    config_dict,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

            self._show_status(f"配置已保存到 {self._config_path}")
            self.config_saved = True
            QMessageBox.information(
                self, "保存成功",
                f"配置已保存到:\n{os.path.abspath(self._config_path)}\n\n"
                f"原文件已备份为 {self._config_path}.bak"
            )

        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _reload_config(self):
        """重新加载配置文件"""
        reply = QMessageBox.question(
            self, "重新加载",
            "重新加载将丢弃当前未保存的修改，确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from config_loader import load_config
            self._config = load_config(self._config_path)

            # 刷新所有页面
            self._servers_page._config = self._config
            self._servers_page._load_from_config()

            self._devices_page._config = self._config
            self._devices_page._load_from_config()

            self._scheduler_page._config = self._config
            self._scheduler_page._load_from_config()

            self._database_page._config = self._config
            self._database_page._load_from_config()

            self._show_status("配置已重新加载")

        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
