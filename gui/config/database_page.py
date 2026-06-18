"""
配置界面 — 数据库配置页
===========================
MySQL/PostgreSQL引擎选择、连接参数、连接测试、建表初始化。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
    QMessageBox, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt

from gui.shared.styles import COLORS

_INPUT_HEIGHT = 30


def _fix_height(widget):
    widget.setFixedHeight(_INPUT_HEIGHT)
    return widget


class DatabasePage(QWidget):
    """数据库配置页"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._setup_ui()
        self._load_from_config()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("数据库配置")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel("配置采集数据的存储引擎和连接参数")
        subtitle.setObjectName("hintText")
        layout.addWidget(subtitle)

        # ---- 引擎选择 ----
        engine_group = QGroupBox("数据库引擎")
        engine_layout = QFormLayout(engine_group)
        engine_layout.setSpacing(8)
        engine_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        engine_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._engine_combo = _fix_height(QComboBox())
        self._engine_combo.addItems(["mysql", "postgresql"])
        self._engine_combo.currentTextChanged.connect(self._on_engine_changed)
        engine_layout.addRow("引擎:", self._engine_combo)

        layout.addWidget(engine_group)

        # ---- 连接参数 ----
        conn_group = QGroupBox("连接参数")
        conn_layout = QFormLayout(conn_group)
        conn_layout.setSpacing(8)
        conn_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        conn_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._host_edit = _fix_height(QLineEdit())
        self._host_edit.setPlaceholderText("localhost 或远程IP")
        conn_layout.addRow("主机:", self._host_edit)

        self._port_spin = _fix_height(QSpinBox())
        self._port_spin.setRange(1, 65535)
        conn_layout.addRow("端口:", self._port_spin)

        self._username_edit = _fix_height(QLineEdit())
        conn_layout.addRow("用户名:", self._username_edit)

        self._password_edit = _fix_height(QLineEdit())
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        conn_layout.addRow("密码:", self._password_edit)

        self._database_edit = _fix_height(QLineEdit())
        self._database_edit.setPlaceholderText("数据库名称")
        conn_layout.addRow("数据库:", self._database_edit)

        layout.addWidget(conn_group)

        # ---- 操作按钮 ----
        btn_layout = QHBoxLayout()

        self._test_btn = QPushButton("测试连接")
        self._test_btn.clicked.connect(self._test_connection)
        btn_layout.addWidget(self._test_btn)

        self._init_btn = QPushButton("初始化数据表")
        self._init_btn.clicked.connect(self._init_tables)
        btn_layout.addWidget(self._init_btn)

        btn_layout.addStretch()

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"font-size: 12px;")
        btn_layout.addWidget(self._status_label)

        layout.addLayout(btn_layout)

        # ---- 说明 ----
        info_group = QGroupBox("说明")
        info_layout = QVBoxLayout(info_group)
        info_text = QLabel(
            "点击\"初始化数据表\"将创建采集数据表：\n"
            "• plc_data — 统一采集数据表（所有设备类型共用，字段数据以JSON存储）\n\n"
            "设备类型定义表（device_type_def）通过导入新设备时自动创建和维护。"
        )
        info_text.setObjectName("hintText")
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        layout.addWidget(info_group)

        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _on_engine_changed(self, engine: str):
        """切换引擎时更新默认端口"""
        if engine == "mysql":
            self._port_spin.setValue(3306)
        elif engine == "postgresql":
            self._port_spin.setValue(5432)

    def _load_from_config(self):
        """从配置加载"""
        db = self._config.database

        idx = self._engine_combo.findText(db.engine)
        if idx >= 0:
            self._engine_combo.setCurrentIndex(idx)

        self._host_edit.setText(str(db.host))
        self._port_spin.setValue(int(db.port))
        self._username_edit.setText(str(db.username))
        self._password_edit.setText(str(db.password))
        self._database_edit.setText(str(db.database))

    def _test_connection(self):
        """测试数据库连接"""
        self._status_label.setText("连接中...")
        self._status_label.setStyleSheet(f"color: {COLORS['accent_yellow']};")
        self._test_btn.setEnabled(False)

        try:
            from config_loader import DatabaseConfig
            from sqlalchemy import create_engine, text

            db_cfg = self._get_db_config()
            if db_cfg.engine == "mysql":
                url = (
                    f"mysql+pymysql://{db_cfg.username}:{db_cfg.password}"
                    f"@{db_cfg.host}:{db_cfg.port}/{db_cfg.database}"
                    f"?charset=utf8mb4"
                )
            else:
                url = (
                    f"postgresql+psycopg2://{db_cfg.username}:{db_cfg.password}"
                    f"@{db_cfg.host}:{db_cfg.port}/{db_cfg.database}"
                )

            engine = create_engine(url, connect_args={"connect_timeout": 5} if db_cfg.engine == "postgresql" else {})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()

            self._status_label.setText("连接成功")
            self._status_label.setStyleSheet(f"color: {COLORS['accent_green']}; font-weight: bold;")

        except Exception as e:
            self._status_label.setText(f"连接失败: {e}")
            self._status_label.setStyleSheet(f"color: {COLORS['accent_red']};")
        finally:
            self._test_btn.setEnabled(True)

    def _init_tables(self):
        """初始化采集数据表"""
        try:
            from config_loader import get_db_url
            from sqlalchemy import create_engine
            from storage.models import PlcData

            db_cfg = self._get_db_config()
            url = get_db_url(db_cfg)
            engine = create_engine(url)
            PlcData.__table__.create(engine, checkfirst=True)
            engine.dispose()

            QMessageBox.information(
                self, "初始化成功",
                f"采集数据表已在 {db_cfg.database} 数据库中创建/更新完成。\n"
                f"表: plc_data（采集数据）"
            )
        except Exception as e:
            QMessageBox.critical(self, "初始化失败", str(e))

    def _get_db_config(self):
        """从当前页面构造DatabaseConfig"""
        from config_loader import DatabaseConfig
        return DatabaseConfig(
            engine=self._engine_combo.currentText(),
            host=self._host_edit.text().strip(),
            port=self._port_spin.value(),
            username=self._username_edit.text().strip(),
            password=self._password_edit.text(),
            database=self._database_edit.text().strip(),
        )

    def save_to_dict(self) -> dict:
        """导出配置字典"""
        return {
            "database": {
                "engine": self._engine_combo.currentText(),
                "host": self._host_edit.text().strip(),
                "port": self._port_spin.value(),
                "username": self._username_edit.text().strip(),
                "password": self._password_edit.text(),
                "database": self._database_edit.text().strip(),
            },
        }

    def validate(self) -> list:
        """校验"""
        errors = []
        if not self._host_edit.text().strip():
            errors.append("数据库主机不能为空")
        if not self._database_edit.text().strip():
            errors.append("数据库名称不能为空")
        if not self._username_edit.text().strip():
            errors.append("数据库用户名不能为空")
        return errors
