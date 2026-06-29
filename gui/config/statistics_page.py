"""
配置界面 — 统计配置页
========================
为每种设备类型选择一个主要统计字段（单选），用于 MES 系统调取实时数据。
同类型所有设备共用同一个统计字段。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QComboBox, QScrollArea, QFrame, QGroupBox, QFormLayout,
)
from PySide6.QtCore import Qt

from gui.shared.styles import COLORS
from protocol.device_types import get_safe, list_types


_INPUT_HEIGHT = 30


def _fix_height(widget):
    widget.setFixedHeight(_INPUT_HEIGHT)
    return widget


def _get_available_fields(device_type: str) -> list:
    """获取设备类型的所有可用字段"""
    parser = get_safe(device_type)
    if not parser:
        return []

    fields = []
    # parse_rules 产生的字段
    for rule in getattr(parser, '_parse_rules', []):
        key = rule.get("field", "")
        if key:
            fields.append({"key": key, "label": key})

    # bit_fields 产生的字段
    for bf in getattr(parser, '_bit_fields', []) or []:
        prefix = bf.get("prefix", "")
        for bit_def in bf.get("bits", {}).values():
            key = f"{prefix}{bit_def['name']}"
            label = bit_def.get("label", bit_def["name"])
            fields.append({"key": key, "label": f"{label} ({key})"})

    return fields


class StatisticsPage(QWidget):
    """统计配置页 — 每种设备类型选择一个主要数据字段"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._combos = {}  # device_type -> QComboBox
        self._setup_ui()

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
        title = QLabel("统计配置")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "为每种设备类型选择一个主要数据字段，该字段的实时值将写入设备注册表，"
            "方便 MES 系统调取。同类型所有设备共用同一个统计字段。"
        )
        subtitle.setObjectName("hintText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # 当前已配置的统计字段
        stats_config = getattr(self._config, 'statistics_config', {}) or {}

        # 按设备类型列出
        group = QGroupBox("设备类型")
        group_layout = QFormLayout(group)
        group_layout.setSpacing(8)
        group_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        group_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        for type_key, display_name in list_types():
            combo = _fix_height(QComboBox())
            combo.addItem("（不统计）", "")

            fields = _get_available_fields(type_key)
            for f in fields:
                combo.addItem(f["label"], f["key"])

            # 设置当前选中值
            current_key = stats_config.get(type_key, '')
            if current_key:
                idx = combo.findData(current_key)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            group_layout.addRow(f"{display_name} ({type_key})", combo)
            self._combos[type_key] = combo

        layout.addWidget(group)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def save_to_dict(self) -> dict:
        """导出统计配置（device_type -> value_key）"""
        statistics_config = {}
        for type_key, combo in self._combos.items():
            key = combo.currentData() or ""
            if key:
                statistics_config[type_key] = key
        return {"statistics_config": statistics_config}

    def validate(self) -> list:
        """校验（无特殊要求）"""
        return []
