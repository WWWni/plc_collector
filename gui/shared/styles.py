"""
工业深色主题样式表
==================
深蓝/深灰底色，亮色数据文字，适合工业现场长时间查看。
"""

# 颜色常量
COLORS = {
    "bg_primary": "#1a1f2e",      # 主背景 - 深蓝灰
    "bg_secondary": "#232839",    # 次背景 - 卡片底色
    "bg_input": "#2a3040",        # 输入框底色
    "border": "#3a4055",          # 边框色
    "text_primary": "#e8ecf4",    # 主文字 - 亮白
    "text_secondary": "#8892a8",  # 次文字 - 灰蓝
    "text_dim": "#5a6478",        # 暗文字
    "accent_blue": "#4a9eff",     # 主色调 - 亮蓝
    "accent_green": "#34d399",    # 成功/运行 - 亮绿
    "accent_yellow": "#fbbf24",   # 警告/点动 - 亮黄
    "accent_red": "#f87171",      # 故障/告警 - 亮红
    "accent_orange": "#fb923c",   # 注意 - 橙色
    "status_running": "#34d399",  # 运行状态
    "status_jogging": "#fbbf24",  # 点动状态
    "status_stopped": "#6b7280",  # 停止状态
    "status_fault": "#f87171",    # 故障状态
    "status_offline": "#4b5563",  # 离线状态
}

MAIN_STYLE = f"""
/* ---- 全局 ---- */
QMainWindow, QDialog {{
    background-color: {COLORS['bg_primary']};
    color: {COLORS['text_primary']};
}}

QWidget {{
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {COLORS['text_primary']};
}}

/* ---- 菜单栏 ---- */
QMenuBar {{
    background-color: {COLORS['bg_secondary']};
    border-bottom: 1px solid {COLORS['border']};
    padding: 2px;
}}
QMenuBar::item {{
    padding: 6px 12px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background-color: {COLORS['accent_blue']};
    border-radius: 4px;
}}

/* ---- 工具栏 ---- */
QToolBar {{
    background-color: {COLORS['bg_secondary']};
    border-bottom: 1px solid {COLORS['border']};
    padding: 4px;
    spacing: 8px;
}}

/* ---- 按钮 ---- */
QPushButton {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {COLORS['border']};
    border-color: {COLORS['accent_blue']};
}}
QPushButton:pressed {{
    background-color: {COLORS['accent_blue']};
}}
QPushButton:disabled {{
    color: {COLORS['text_dim']};
    border-color: {COLORS['bg_input']};
}}
QPushButton#primaryBtn {{
    background-color: {COLORS['accent_blue']};
    border: none;
    color: white;
}}
QPushButton#primaryBtn:hover {{
    background-color: #5aadff;
}}
QPushButton#dangerBtn {{
    background-color: {COLORS['accent_red']};
    border: none;
    color: white;
}}
QPushButton#secondaryBtn {{
    background-color: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    color: {COLORS['text_secondary']};
}}
QPushButton#secondaryBtn:hover {{
    background-color: {COLORS['border']};
    border-color: {COLORS['accent_blue']};
    color: {COLORS['text_primary']};
}}
QPushButton#secondaryBtn:disabled {{
    border-color: {COLORS['bg_input']};
    color: {COLORS['text_dim']};
}}

/* ---- 输入框 ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {COLORS['accent_blue']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {COLORS['accent_blue']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLORS['border']};
    border-bottom: 1px solid {COLORS['border']};
    background: {COLORS['bg_input']};
    border-top-right-radius: 6px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
    border-left: 1px solid {COLORS['border']};
    background: {COLORS['bg_input']};
    border-bottom-right-radius: 6px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {COLORS['border']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_secondary']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent_blue']};
}}

/* ---- 表格 ---- */
QTableWidget, QTableView {{
    background-color: {COLORS['bg_secondary']};
    alternate-background-color: {COLORS['bg_primary']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    gridline-color: {COLORS['border']};
    selection-background-color: rgba(74, 158, 255, 0.25);
}}
QTableWidget::item, QTableView::item {{
    padding: 6px;
}}
QHeaderView::section {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_secondary']};
    border: none;
    border-bottom: 2px solid {COLORS['accent_blue']};
    padding: 8px 6px;
    font-weight: bold;
}}

/* ---- Tab页 ---- */
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-top: none;
    background-color: {COLORS['bg_primary']};
}}
QTabBar::tab {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['text_secondary']};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 20px;
    margin-right: 0;
    min-width: 80px;
}}
QTabBar::tab:selected {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['accent_blue']};
    border-bottom: 2px solid {COLORS['accent_blue']};
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    color: {COLORS['text_primary']};
    border-bottom: 2px solid {COLORS['text_dim']};
}}

/* ---- 分组框 ---- */
QGroupBox {{
    background-color: {COLORS['bg_secondary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 20px;
    font-weight: bold;
    color: {COLORS['accent_blue']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 6px;
}}

/* ---- 滚动条 ---- */
QScrollBar:vertical {{
    background-color: {COLORS['bg_primary']};
    width: 14px;
    border-radius: 7px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {COLORS['text_dim']};
    border-radius: 7px;
    min-height: 40px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['accent_blue']};
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background-color: {COLORS['bg_primary']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background-color: {COLORS['bg_primary']};
    height: 14px;
    border-radius: 7px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {COLORS['text_dim']};
    border-radius: 7px;
    min-width: 40px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS['accent_blue']};
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background-color: {COLORS['bg_primary']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---- 状态栏 ---- */
QStatusBar {{
    background-color: {COLORS['bg_secondary']};
    border-top: 1px solid {COLORS['border']};
    color: {COLORS['text_secondary']};
}}

/* ---- 标签 ---- */
QLabel {{
    color: {COLORS['text_primary']};
}}
QLabel#sectionTitle {{
    font-size: 16px;
    font-weight: bold;
    color: {COLORS['accent_blue']};
}}
QLabel#hintText {{
    color: {COLORS['text_dim']};
    font-size: 12px;
}}

/* ---- 复选框 ---- */
QCheckBox {{
    spacing: 8px;
    color: {COLORS['text_primary']};
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid {COLORS['border']};
    background-color: {COLORS['bg_input']};
}}
QCheckBox::indicator:checked {{
    background-color: {COLORS['accent_blue']};
    border-color: {COLORS['accent_blue']};
}}

/* ---- 滑块 ---- */
QSlider::groove:horizontal {{
    height: 6px;
    background: {COLORS['bg_input']};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {COLORS['accent_blue']};
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}}

/* ---- 列表 ---- */
QListWidget {{
    background-color: {COLORS['bg_secondary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    alternate-background-color: {COLORS['bg_primary']};
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: rgba(74, 158, 255, 0.25);
    color: {COLORS['accent_blue']};
}}

/* ---- 分割器 ---- */
QSplitter::handle {{
    background-color: {COLORS['border']};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}

/* ---- 文本框 ---- */
QTextEdit, QPlainTextEdit {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px;
    font-family: "Consolas", "Courier New", monospace;
}}
"""
