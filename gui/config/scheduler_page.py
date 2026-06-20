"""
配置界面 — 采集参数与日志配置页
====================================
采集间隔、批量读取开关、日志级别和日志文件路径。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QSpinBox, QDoubleSpinBox, QSlider, QCheckBox, QComboBox, QLineEdit,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt

from gui.shared.styles import COLORS

_INPUT_HEIGHT = 30


def _fix_height(widget):
    widget.setFixedHeight(_INPUT_HEIGHT)
    return widget


class SchedulerPage(QWidget):
    """采集参数与日志配置页"""

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
        title = QLabel("采集参数与日志")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel("配置数据采集间隔和日志输出参数")
        subtitle.setObjectName("hintText")
        layout.addWidget(subtitle)

        # ---- 采集参数 ----
        sched_group = QGroupBox("采集参数")
        sched_layout = QVBoxLayout(sched_group)

        # 采集间隔: 滑块 + 数值
        interval_row = QHBoxLayout()
        interval_row.setSpacing(16)
        interval_row.addWidget(QLabel("采集间隔:"))

        self._interval_slider = QSlider(Qt.Orientation.Horizontal)
        self._interval_slider.setRange(1, 60)
        self._interval_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._interval_slider.setTickInterval(5)
        self._interval_slider.setFixedHeight(30)
        self._interval_slider.valueChanged.connect(self._on_interval_changed)
        interval_row.addWidget(self._interval_slider, 1)

        self._interval_spin = _fix_height(QSpinBox())
        self._interval_spin.setRange(1, 60)
        self._interval_spin.setSuffix(" 秒")
        self._interval_spin.setFixedWidth(90)
        self._interval_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._interval_spin.valueChanged.connect(self._on_interval_spin_changed)
        interval_row.addWidget(self._interval_spin)

        sched_layout.addLayout(interval_row)

        # 间隔提示
        self._interval_hint = QLabel()
        self._interval_hint.setObjectName("hintText")
        sched_layout.addWidget(self._interval_hint)

        # Modbus超时和重试
        modbus_row = QHBoxLayout()
        modbus_row.setSpacing(16)
        modbus_row.addWidget(QLabel("Modbus读取超时:"))
        self._modbus_timeout_spin = _fix_height(QDoubleSpinBox())
        self._modbus_timeout_spin.setRange(0.1, 30.0)
        self._modbus_timeout_spin.setSingleStep(0.1)
        self._modbus_timeout_spin.setDecimals(1)
        self._modbus_timeout_spin.setSuffix(" 秒")
        self._modbus_timeout_spin.setFixedWidth(100)
        modbus_row.addWidget(self._modbus_timeout_spin)
        modbus_row.addSpacing(20)
        modbus_row.addWidget(QLabel("Modbus重试:"))
        self._modbus_retry_spin = _fix_height(QSpinBox())
        self._modbus_retry_spin.setRange(0, 10)
        self._modbus_retry_spin.setSuffix(" 次")
        self._modbus_retry_spin.setFixedWidth(100)
        modbus_row.addWidget(self._modbus_retry_spin)
        modbus_row.addSpacing(20)
        modbus_row.addWidget(QLabel("重试间隔:"))
        self._modbus_retry_delay_spin = _fix_height(QDoubleSpinBox())
        self._modbus_retry_delay_spin.setRange(0.0, 5.0)
        self._modbus_retry_delay_spin.setSingleStep(0.1)
        self._modbus_retry_delay_spin.setDecimals(1)
        self._modbus_retry_delay_spin.setSuffix(" 秒")
        self._modbus_retry_delay_spin.setFixedWidth(100)
        modbus_row.addWidget(self._modbus_retry_delay_spin)
        modbus_row.addStretch()
        sched_layout.addLayout(modbus_row)

        # Modbus提示
        self._modbus_hint = QLabel("RS485透传建议超时 0.3-0.5 秒、重试 1 次；Modbus TCP 网关可缩短至 0.1-0.2 秒")
        self._modbus_hint.setObjectName("hintText")
        self._modbus_hint.setWordWrap(True)
        sched_layout.addWidget(self._modbus_hint)

        layout.addWidget(sched_group)

        # ---- 日志配置 ----
        log_group = QGroupBox("日志配置")
        log_layout = QFormLayout(log_group)
        log_layout.setSpacing(8)
        log_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        log_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._log_level_combo = _fix_height(QComboBox())
        self._log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        log_layout.addRow("日志级别:", self._log_level_combo)

        self._log_file_edit = _fix_height(QLineEdit())
        self._log_file_edit.setPlaceholderText("logs/collector.log")
        log_layout.addRow("日志文件:", self._log_file_edit)

        self._max_bytes_spin = _fix_height(QSpinBox())
        self._max_bytes_spin.setRange(1, 100)
        self._max_bytes_spin.setSuffix(" MB")
        log_layout.addRow("单文件大小:", self._max_bytes_spin)

        self._backup_spin = _fix_height(QSpinBox())
        self._backup_spin.setRange(1, 20)
        self._backup_spin.setSuffix(" 个")
        log_layout.addRow("备份数量:", self._backup_spin)

        layout.addWidget(log_group)

        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _on_interval_changed(self, value):
        """滑块值变化 → 同步SpinBox"""
        self._interval_spin.blockSignals(True)
        self._interval_spin.setValue(value)
        self._interval_spin.blockSignals(False)
        self._update_interval_hint(value)

    def _on_interval_spin_changed(self, value):
        """SpinBox值变化 → 同步滑块"""
        self._interval_slider.blockSignals(True)
        self._interval_slider.setValue(value)
        self._interval_slider.blockSignals(False)
        self._update_interval_hint(value)

    def _update_interval_hint(self, value):
        if value < 2:
            self._interval_hint.setText(
                "注意: 9600bps下采集间隔建议不低于2秒，过短可能导致RS485总线拥堵"
            )
            self._interval_hint.setStyleSheet(
                f"color: {COLORS['accent_yellow']}; font-size: 12px;"
            )
        elif value > 10:
            self._interval_hint.setText(f"每 {value} 秒采集一次，数据实时性较低")
            self._interval_hint.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 12px;"
            )
        else:
            self._interval_hint.setText("推荐范围 (2-10秒)")
            self._interval_hint.setStyleSheet(
                f"color: {COLORS['accent_green']}; font-size: 12px;"
            )

    def _load_from_config(self):
        """从配置加载"""
        sched = self._config.scheduler
        log = self._config.logging

        self._interval_slider.setValue(sched.interval_seconds)
        self._interval_spin.setValue(sched.interval_seconds)
        self._modbus_timeout_spin.setValue(sched.timeout)
        self._modbus_retry_spin.setValue(sched.retry)
        self._modbus_retry_delay_spin.setValue(sched.retry_delay)

        idx = self._log_level_combo.findText(log.level)
        if idx >= 0:
            self._log_level_combo.setCurrentIndex(idx)

        self._log_file_edit.setText(log.file)
        self._max_bytes_spin.setValue(log.max_bytes // (1024 * 1024))
        self._backup_spin.setValue(log.backup_count)

    def save_to_dict(self) -> dict:
        """导出配置字典"""
        return {
            "scheduler": {
                "interval_seconds": self._interval_spin.value(),
                "batch_read": True,
                "timeout": self._modbus_timeout_spin.value(),
                "retry": self._modbus_retry_spin.value(),
                "retry_delay": self._modbus_retry_delay_spin.value(),
            },
            "logging": {
                "level": self._log_level_combo.currentText(),
                "file": self._log_file_edit.text().strip() or "logs/collector.log",
                "max_bytes": self._max_bytes_spin.value() * 1024 * 1024,
                "backup_count": self._backup_spin.value(),
            },
        }

    def validate(self) -> list:
        """校验"""
        errors = []
        if self._interval_spin.value() < 1:
            errors.append("采集间隔不能小于1秒")
        return errors
