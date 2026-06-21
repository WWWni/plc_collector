"""
实时数据面板 Tab
================
卡片式布局，每台设备一张紧凑卡片。
显示字段由设备配置的 display_fields 驱动，支持逐设备自定义。
支持多串口服务器架构。
"""

from PySide6.QtWidgets import (
    QWidget, QGridLayout, QScrollArea, QVBoxLayout, QFrame, QLabel,
    QSizePolicy, QHBoxLayout,
)
from PySide6.QtCore import Qt
from typing import Dict, List, Any, Tuple

from gui.shared.styles import COLORS
from protocol.device_types import get_safe


# 通用默认颜色（status_map 中未定义时使用）
_DEFAULT_COLOR = "#9e9e9e"


def _get_status_info(run_mode: str, status_map: dict) -> Tuple[str, str]:
    """获取状态对应的颜色和文字，全部从设备类型的 status_map 获取"""
    if status_map and run_mode in status_map:
        info = status_map[run_mode]
        return info.get("color", _DEFAULT_COLOR), info.get("text", run_mode)
    return _DEFAULT_COLOR, run_mode


def _format_field_value(value, field_def: dict, data: dict) -> str:
    """根据格式定义格式化字段值"""
    fmt = field_def.get("format", "s")

    # gear 格式特殊处理：从子字段读取，不依赖 value
    if fmt == "gear":
        fields = field_def.get("fields", [])
        if len(fields) >= 2:
            run_gear = data.get(fields[0], 0)
            jog_gear = data.get(fields[1], 0)
            return f"{run_gear} / {jog_gear}"
        return "—"

    if value is None:
        return "—"

    if fmt == ".1f":
        return f"{value:.1f}"
    elif fmt == ".2f":
        return f"{value:.2f}"
    elif fmt == ",":
        return f"{value:,}"
    elif fmt == "s":
        return str(value)
    else:
        return str(value)


class DeviceCard(QFrame):
    """单台设备的紧凑卡片 — 字段由展示配置驱动"""

    def __init__(self, device_name: str, slave_addr: int,
                 server_name: str = "", device_type: str = "",
                 display_fields: list = None,
                 parent=None):
        super().__init__(parent)
        self.slave_addr = slave_addr
        self.device_name = device_name
        self.server_name = server_name
        self.device_type = device_type
        self._type_def = get_safe(device_type)
        self._display_fields = display_fields or []
        self._data_labels: Dict[str, QLabel] = {}
        self._unit_labels: Dict[str, QLabel] = {}

        self._setup_ui()
        self.set_offline()

    def _setup_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            DeviceCard {{
                background-color: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMaximumWidth(185)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(6, 4, 6, 4)
        self._main_layout.setSpacing(2)

        # ---- 头部: 设备名 + 状态 ----
        header = QHBoxLayout()
        header.setSpacing(4)

        # 设备名（含服务器标识）
        display_name = self.device_name
        if self.server_name:
            short_srv = self.server_name[:6]
            display_name = f"[{short_srv}] {self.device_name}"
        self._name_label = QLabel(display_name)
        self._name_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {COLORS['text_primary']};"
        )
        header.addWidget(self._name_label)
        header.addStretch()

        offline_color, offline_text = _get_status_info("offline", getattr(self._type_def, 'STATUS_MAP', {}))
        self._status_label = QLabel(f"● {offline_text}")
        self._status_label.setStyleSheet(
            f"font-size: 10px; color: {offline_color}; font-weight: bold;"
        )
        header.addWidget(self._status_label)
        self._main_layout.addLayout(header)

        # ---- 数据区: 由 display_fields 驱动 ----
        self._build_data_area()

    def _build_data_area(self):
        """构建/重建数据展示区"""
        # 清除旧的数据区
        if hasattr(self, '_data_grid_widget') and self._data_grid_widget:
            self._main_layout.removeWidget(self._data_grid_widget)
            self._data_grid_widget.deleteLater()
        self._data_labels.clear()
        self._unit_labels.clear()

        self._data_grid_widget = QWidget()
        data_grid = QGridLayout(self._data_grid_widget)
        data_grid.setContentsMargins(0, 0, 0, 0)
        data_grid.setHorizontalSpacing(4)
        data_grid.setVerticalSpacing(1)

        for row, field_def in enumerate(self._display_fields):
            key = field_def["key"]
            label_text = field_def["label"]
            unit_text = field_def.get("unit", "")

            name_lbl = QLabel(label_text)
            name_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11px;"
            )
            data_grid.addWidget(name_lbl, row, 0)

            value_lbl = QLabel("—")
            value_lbl.setStyleSheet(
                f"color: {COLORS['text_primary']}; "
                f"font-size: 12px; font-weight: bold;"
            )
            value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            data_grid.addWidget(value_lbl, row, 1)

            self._data_labels[key] = value_lbl

            if unit_text and unit_text != "dynamic":
                unit_lbl = QLabel(unit_text)
                unit_lbl.setStyleSheet(
                    f"color: {COLORS['text_dim']}; font-size: 10px;"
                )
                data_grid.addWidget(unit_lbl, row, 2)
                self._unit_labels[key] = unit_lbl

        self._main_layout.addWidget(self._data_grid_widget)

    def update_data(self, data: dict):
        """用采集数据更新卡片"""
        run_mode = data.get("run_mode", "unknown")
        active_faults = data.get("active_faults", [])
        status_map = getattr(self._type_def, 'STATUS_MAP', None) or {}

        if active_faults:
            status_key = "fault"
            status_color, status_text = _get_status_info("fault", status_map)
            border_width = "2px"
        else:
            status_key = run_mode
            status_color, status_text = _get_status_info(run_mode, status_map)
            border_width = "1px"

        self._status_label.setText(f"● {status_text}")
        self._status_label.setStyleSheet(
            f"font-size: 11px; color: {status_color}; font-weight: bold;"
        )
        self.setStyleSheet(f"""
            DeviceCard {{
                background-color: {COLORS['bg_secondary']};
                border: {border_width} solid {status_color};
                border-radius: 4px;
            }}
        """)

        # 按 display_fields 更新数据
        for field_def in self._display_fields:
            key = field_def["key"]
            value = data.get(key)

            if key in self._data_labels:
                self._data_labels[key].setText(
                    _format_field_value(value, field_def, data)
                )

            # 动态单位 (如计米器的"米"/"码")
            if field_def.get("unit") == "dynamic" and key in self._unit_labels:
                unit_text = data.get("unit_text", "")
                self._unit_labels[key].setText(unit_text)

    def set_offline(self):
        """设置卡片为离线状态"""
        offline_color, offline_text = _get_status_info("offline", getattr(self._type_def, 'STATUS_MAP', {}))
        self._status_label.setText(f"● {offline_text}")
        self._status_label.setStyleSheet(
            f"font-size: 11px; color: {offline_color}; font-weight: bold;"
        )
        self.setStyleSheet(f"""
            DeviceCard {{
                background-color: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
        """)
        for lbl in self._data_labels.values():
            lbl.setText("—")


class DashboardTab(QWidget):
    """实时数据面板Tab — 卡片网格布局"""

    def __init__(self, config, parent=None):
        """
        Args:
            config: AppConfig实例（包含 servers 列表）
        """
        super().__init__(parent)
        # 复合键: (server_index, slave_addr) -> DeviceCard
        self._cards: Dict[Tuple[int, int], DeviceCard] = {}
        self._setup_ui(config)

    def _setup_ui(self, config):
        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        # 卡片网格容器
        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(2, 2, 2, 2)
        self._grid_layout.setSpacing(3)

        # 展示配置：从 config.display_config 读取
        display_config = getattr(config, 'display_config', {}) or {}

        # 构建扁平化设备列表并创建卡片
        all_devices = []
        for srv_idx, srv in enumerate(config.servers):
            for dev_cfg in srv.devices:
                all_devices.append((srv_idx, srv.name, dev_cfg))

        cols = 5
        for i, (srv_idx, srv_name, dev_cfg) in enumerate(all_devices):
            dev_type = getattr(dev_cfg, 'device_type', '')
            # 从 display_config 按设备类型查找展示字段，未配置则从注册表取默认值
            fields = display_config.get(dev_type)
            if fields is None:
                type_def = get_safe(dev_type)
                fields = getattr(type_def, 'DISPLAY_FIELDS', []) if type_def else []
            card = DeviceCard(
                device_name=dev_cfg.name,
                slave_addr=dev_cfg.slave_addr,
                server_name=srv_name,
                device_type=dev_type,
                display_fields=fields,
            )
            row = i // cols
            col = i % cols
            self._grid_layout.addWidget(card, row, col)
            self._cards[(srv_idx, dev_cfg.slave_addr)] = card

        # 弹簧占位
        total_rows = (len(all_devices) + cols - 1) // cols
        self._grid_layout.setRowStretch(total_rows, 1)

        scroll.setWidget(self._grid_widget)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

    def refresh_type_defs(self):
        """DB更新后刷新所有卡片的type_def（从注册表获取最新定义）"""
        for card in self._cards.values():
            card._type_def = get_safe(card.device_type)
            card.set_offline()

    def update_devices(self, data_list: List[dict]):
        """
        更新设备数据（由MonitorMainWindow调用）

        Args:
            data_list: 本轮采集的设备数据字典列表
        """
        updated_keys = set()
        for data in data_list:
            srv_idx = data.get("server_index", 0)
            addr = data.get("slave_addr")
            key = (srv_idx, addr)
            if key in self._cards:
                self._cards[key].update_data(data)
                updated_keys.add(key)

        # 未更新的设备标记为离线
        for key, card in self._cards.items():
            if key not in updated_keys:
                card.set_offline()
