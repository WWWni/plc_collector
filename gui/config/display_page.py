"""
配置界面 — 展示配置页
========================
按设备类型配置仪表板卡片展示的字段。
每种设备类型独立配置，同类型所有设备共享同一套展示字段。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QCheckBox, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt

from gui.shared.styles import COLORS
from protocol.device_types import list_types, get_safe


_INPUT_HEIGHT = 30


class DisplayPage(QWidget):
    """展示配置页 — 按设备类型选择仪表板卡片展示的字段"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._type_checkboxes: dict = {}  # {type_key: [(QCheckBox, field_def), ...]}
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
        title = QLabel("展示配置")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel("为每种设备类型选择仪表板卡片上展示的字段，同类型设备共享配置")
        subtitle.setObjectName("hintText")
        layout.addWidget(subtitle)

        # 当前已配置的展示字段
        saved_config = getattr(self._config, 'display_config', {}) or {}

        # 遍历所有注册的设备类型
        for type_key, display_name in list_types():
            parser = get_safe(type_key)
            if parser is None:
                continue

            group = QGroupBox(f"{display_name} ({type_key})")
            group_layout = QVBoxLayout(group)
            group_layout.setSpacing(4)

            # 获取该类型的所有可用字段
            available_fields = self._get_available_fields(parser)

            # 确定预选字段
            if type_key in saved_config:
                selected_keys = {f["key"] for f in saved_config[type_key]}
            else:
                # 首次：使用设备类型的默认展示字段
                defaults = getattr(parser, 'DISPLAY_FIELDS', []) or []
                selected_keys = {f["key"] for f in defaults}

            checkboxes = []
            for field in available_fields:
                cb = QCheckBox(f"{field['label']}  ({field['key']})")
                cb.setChecked(field["key"] in selected_keys)
                cb.setStyleSheet("font-size: 12px; padding: 2px 0;")
                group_layout.addWidget(cb)
                checkboxes.append((cb, field))

            if not available_fields:
                hint = QLabel("该设备类型无可展示字段")
                hint.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
                group_layout.addWidget(hint)

            self._type_checkboxes[type_key] = checkboxes
            layout.addWidget(group)

        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    @staticmethod
    def _get_available_fields(parser) -> list:
        """
        构建完整的可展示字段列表。
        以 DISPLAY_FIELDS 为主源（保留 unit/format 完整元数据），
        再用 parse_rules / bit_fields 补充不在 DISPLAY_FIELDS 中的字段。
        """
        # 1. DISPLAY_FIELDS 作为主源（有完整的 key/label/unit/format）
        display_fields = getattr(parser, 'DISPLAY_FIELDS', []) or []
        fields_by_key = {f["key"]: dict(f) for f in display_fields}

        # 2. 从 parse_rules 补充缺失的字段
        for rule in getattr(parser, '_parse_rules', []):
            key = rule["field"]
            if key not in fields_by_key:
                fields_by_key[key] = {"key": key, "label": key, "unit": "", "format": "s"}

        # 3. 从 bit_fields 补充缺失的字段
        for bf in getattr(parser, '_bit_fields', []) or []:
            prefix = bf.get("prefix", "")
            for bit_def in bf.get("bits", {}).values():
                key = f"{prefix}{bit_def['name']}"
                if key not in fields_by_key:
                    fields_by_key[key] = {
                        "key": key,
                        "label": bit_def.get("label", bit_def["name"]),
                        "unit": "",
                        "format": "s",
                    }

        # 保持顺序：DISPLAY_FIELDS 优先，后面按添加顺序
        result = list(display_fields)
        seen = {f["key"] for f in result}
        for key, field_def in fields_by_key.items():
            if key not in seen:
                result.append(field_def)
        return result

    def save_to_dict(self) -> dict:
        """导出展示配置字典"""
        display_config = {}
        for type_key, checkboxes in self._type_checkboxes.items():
            selected = []
            for cb, field_def in checkboxes:
                if cb.isChecked():
                    selected.append(field_def)
            if selected:
                display_config[type_key] = selected
        return {"display_config": display_config}

    def validate(self) -> list:
        """校验（无特殊要求）"""
        return []
