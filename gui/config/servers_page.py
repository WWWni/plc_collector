"""
配置界面 — 串口服务器管理页
=================================
管理多台ZLAN5143D串口服务器的连接参数和串口设置。
左侧服务器列表 + 右侧选中服务器的详细配置。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QSpinBox, QComboBox, QFrame, QScrollArea,
    QSizePolicy, QPushButton, QListWidget, QListWidgetItem,
    QMessageBox, QSplitter, QStackedWidget,
)
from PySide6.QtCore import Qt

from gui.shared.styles import COLORS

# 统一输入框高度
_INPUT_HEIGHT = 30


def _fix_height(widget):
    """给输入控件设置固定高度，确保与QLabel对齐"""
    widget.setFixedHeight(_INPUT_HEIGHT)
    return widget


# ------------------------------------------------------------------
# 服务器数据结构（GUI内部使用，轻量级）
# ------------------------------------------------------------------

class _ServerData:
    """单台服务器的GUI数据模型"""

    def __init__(self, name="串口服务器1", mode="modbus_tcp",
                 host="192.168.1.200", port=4196, tcp_timeout=1,
                 baudrate=9600, data_bits=8, stop_bits=1, parity="none"):
        self.name = name
        self.mode = mode
        self.host = host
        self.port = port
        self.tcp_timeout = tcp_timeout
        self.baudrate = baudrate
        self.data_bits = data_bits
        self.stop_bits = stop_bits
        self.parity = parity

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "connection": {
                "mode": self.mode,
                "host": self.host,
                "port": self.port,
                "tcp_timeout": self.tcp_timeout,
            },
            "serial": {
                "baudrate": self.baudrate,
                "data_bits": self.data_bits,
                "stop_bits": self.stop_bits,
                "parity": self.parity,
            },
        }


class ServersPage(QWidget):
    """串口服务器管理页"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._servers: list[_ServerData] = []
        self._setup_ui()
        self._load_from_config()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(12)

        # 标题
        title = QLabel("服务器管理")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        subtitle = QLabel("管理多台ZLAN5143D串口服务器的网络连接与串口参数")
        subtitle.setObjectName("hintText")
        outer.addWidget(subtitle)

        # ---- 上半部分：服务器列表 + 操作按钮 ----
        list_area = QHBoxLayout()

        # 左侧：服务器列表
        list_frame = QVBoxLayout()
        list_label = QLabel("服务器列表")
        list_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-weight: bold;"
        )
        list_frame.addWidget(list_label)

        self._server_list = QListWidget()
        self._server_list.setFixedWidth(220)
        self._server_list.currentRowChanged.connect(self._on_server_selected)
        list_frame.addWidget(self._server_list)

        # 列表操作按钮
        list_btn_layout = QHBoxLayout()
        add_btn = QPushButton("+ 添加服务器")
        add_btn.setObjectName("primaryBtn")
        add_btn.clicked.connect(self._add_server)
        list_btn_layout.addWidget(add_btn)

        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_server)
        list_btn_layout.addWidget(del_btn)
        list_frame.addLayout(list_btn_layout)

        list_area.addLayout(list_frame)

        # 右侧：选中服务器的详细配置
        self._detail_stack = QStackedWidget()

        # Page 0: 空白提示页
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        hint = QLabel("请从左侧选择或添加一台服务器")
        hint.setObjectName("hintText")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(hint)
        self._detail_stack.addWidget(empty_page)

        # Page 1: 配置表单页（动态填充）
        self._detail_page = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_page)
        self._detail_layout.setContentsMargins(8, 0, 0, 0)
        self._build_detail_form()
        self._detail_stack.addWidget(self._detail_page)

        list_area.addWidget(self._detail_stack, 1)
        outer.addLayout(list_area, 1)

    def _build_detail_form(self):
        """构建右侧详情表单"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        content = QWidget()
        form_outer = QVBoxLayout(content)
        form_outer.setContentsMargins(0, 0, 0, 0)
        form_outer.setSpacing(12)

        # ---- 服务器名称 ----
        name_group = QGroupBox("服务器信息")
        name_layout = QFormLayout(name_group)
        name_layout.setSpacing(8)
        name_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        name_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self._name_edit = _fix_height(QLineEdit())
        self._name_edit.setPlaceholderText("例如: 串口服务器1")
        self._name_edit.textChanged.connect(self._on_name_changed)
        name_layout.addRow("服务器名称:", self._name_edit)
        form_outer.addWidget(name_group)

        # ---- 连接模式区 ----
        mode_group = QGroupBox("连接模式")
        mode_layout = QFormLayout(mode_group)
        mode_layout.setSpacing(8)
        mode_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        mode_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self._mode_combo = _fix_height(QComboBox())
        self._mode_combo.addItems(["modbus_tcp", "tcp_transparent"])
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_layout.addRow("工作模式:", self._mode_combo)

        self._mode_hint = QLabel()
        self._mode_hint.setObjectName("hintText")
        self._mode_hint.setWordWrap(True)
        mode_layout.addRow("", self._mode_hint)
        form_outer.addWidget(mode_group)

        # ---- 网络参数区 ----
        net_group = QGroupBox("网络参数")
        net_layout = QFormLayout(net_group)
        net_layout.setSpacing(8)
        net_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        net_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self._host_edit = _fix_height(QLineEdit())
        self._host_edit.setPlaceholderText("例如: 192.168.1.200")
        net_layout.addRow("ZLAN5143D IP:", self._host_edit)

        self._port_spin = _fix_height(QSpinBox())
        self._port_spin.setRange(1, 65535)
        net_layout.addRow("TCP端口:", self._port_spin)

        self._timeout_spin = _fix_height(QSpinBox())
        self._timeout_spin.setRange(1, 60)
        self._timeout_spin.setSuffix(" 秒")
        net_layout.addRow("TCP连接超时:", self._timeout_spin)
        form_outer.addWidget(net_group)

        # ---- 串口参数区 ----
        serial_group = QGroupBox("串口参数 (RS485)")
        serial_layout = QFormLayout(serial_group)
        serial_layout.setSpacing(8)
        serial_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        serial_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self._baud_combo = _fix_height(QComboBox())
        self._baud_combo.addItems(["9600", "4800", "19200", "38400", "57600", "115200"])
        serial_layout.addRow("波特率:", self._baud_combo)

        self._databits_combo = _fix_height(QComboBox())
        self._databits_combo.addItems(["8", "7", "5", "6"])
        serial_layout.addRow("数据位:", self._databits_combo)

        self._stopbits_combo = _fix_height(QComboBox())
        self._stopbits_combo.addItems(["1", "1.5", "2"])
        serial_layout.addRow("停止位:", self._stopbits_combo)

        self._parity_combo = _fix_height(QComboBox())
        self._parity_combo.addItems(["none", "odd", "even"])
        serial_layout.addRow("校验位:", self._parity_combo)
        form_outer.addWidget(serial_group)

        # ---- ZLAN配置提示 ----
        tip_group = QGroupBox("ZLAN5143D 配置参考")
        tip_layout = QVBoxLayout(tip_group)
        self._tip_label = QLabel()
        self._tip_label.setWordWrap(True)
        self._tip_label.setStyleSheet(
            f"color: {COLORS['accent_yellow']}; font-size: 12px; line-height: 1.6;"
        )
        tip_layout.addWidget(self._tip_label)
        form_outer.addWidget(tip_group)

        form_outer.addStretch()

        scroll.setWidget(content)
        self._detail_layout.addWidget(scroll)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_name_changed(self, text: str):
        row = self._server_list.currentRow()
        if 0 <= row < len(self._servers):
            self._servers[row].name = text.strip() or self._servers[row].name
            self._server_list.item(row).setText(text.strip() or "(未命名)")

    def _on_mode_changed(self, mode: str):
        row = self._server_list.currentRow()
        if 0 <= row < len(self._servers):
            self._servers[row].mode = mode
            if mode == "tcp_transparent":
                self._port_spin.setValue(4196)
                self._servers[row].port = 4196
                self._mode_hint.setText(
                    "TCP透传模式: ZLAN5143D将RS485数据原样透传到TCP，"
                    "由程序自行构造Modbus RTU帧。"
                )
                self._tip_label.setText(
                    "ZLAN5143D设置参考:\n"
                    "  - 工作模式: TCP服务器\n"
                    "  - 转化协议: NONE\n"
                    "  - 端口号: 4196\n"
                    "  - 串口波特率: 9600\n"
                    "  - 数据位: 8, 停止位: 1, 校验: 无"
                )
            else:
                self._port_spin.setValue(502)
                self._servers[row].port = 502
                self._mode_hint.setText(
                    "Modbus TCP网关模式: ZLAN5143D自动完成RTU与TCP协议转换，"
                    "程序使用pymodbus标准接口通信。"
                )
                self._tip_label.setText(
                    "ZLAN5143D设置参考:\n"
                    "  - 工作模式: TCP服务器\n"
                    "  - 转化协议: Modbus TCP\n"
                    "  - 端口号: 502\n"
                    "  - 串口波特率: 9600\n"
                    "  - 数据位: 8, 停止位: 1, 校验: 无"
                )

    def _on_server_selected(self, row: int):
        if 0 <= row < len(self._servers):
            self._detail_stack.setCurrentIndex(1)
            self._load_server_to_form(self._servers[row])
        else:
            self._detail_stack.setCurrentIndex(0)

    def _load_server_to_form(self, srv: _ServerData):
        """将服务器数据加载到表单"""
        # 阻止信号触发循环
        self._name_edit.blockSignals(True)
        self._mode_combo.blockSignals(True)

        self._name_edit.setText(srv.name)
        idx = self._mode_combo.findText(srv.mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        self._host_edit.setText(srv.host)
        self._port_spin.setValue(srv.port)
        self._timeout_spin.setValue(srv.tcp_timeout)

        self._on_mode_changed(srv.mode)  # 更新提示文字

        baud_idx = self._baud_combo.findText(str(srv.baudrate))
        if baud_idx >= 0:
            self._baud_combo.setCurrentIndex(baud_idx)
        db_idx = self._databits_combo.findText(str(srv.data_bits))
        if db_idx >= 0:
            self._databits_combo.setCurrentIndex(db_idx)
        sb_idx = self._stopbits_combo.findText(str(srv.stop_bits))
        if sb_idx >= 0:
            self._stopbits_combo.setCurrentIndex(sb_idx)
        par_idx = self._parity_combo.findText(srv.parity)
        if par_idx >= 0:
            self._parity_combo.setCurrentIndex(par_idx)

        self._name_edit.blockSignals(False)
        self._mode_combo.blockSignals(False)

    def _add_server(self):
        idx = len(self._servers) + 1
        srv = _ServerData(name=f"串口服务器{idx}")
        self._servers.append(srv)
        self._server_list.addItem(QListWidgetItem(srv.name))
        self._server_list.setCurrentRow(len(self._servers) - 1)

    def _delete_server(self):
        row = self._server_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要删除的服务器")
            return
        if len(self._servers) <= 1:
            QMessageBox.warning(self, "提示", "至少需要保留一台服务器")
            return

        name = self._servers[row].name
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除服务器 \"{name}\" 吗？\n"
            f"该服务器下的设备配置将同时丢失。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._servers.pop(row)
            self._server_list.takeItem(row)
            if row < self._server_list.count():
                self._server_list.setCurrentRow(row)
            elif self._server_list.count() > 0:
                self._server_list.setCurrentRow(self._server_list.count() - 1)

    # ------------------------------------------------------------------
    # 数据加载/保存
    # ------------------------------------------------------------------

    def _load_from_config(self):
        """从配置加载"""
        self._server_list.clear()
        self._servers.clear()

        for srv_cfg in self._config.servers:
            srv = _ServerData(
                name=srv_cfg.name,
                mode=srv_cfg.connection.mode,
                host=srv_cfg.connection.host,
                port=srv_cfg.connection.port,
                tcp_timeout=srv_cfg.connection.tcp_timeout,
                baudrate=srv_cfg.serial.baudrate,
                data_bits=srv_cfg.serial.data_bits,
                stop_bits=srv_cfg.serial.stop_bits,
                parity=srv_cfg.serial.parity,
            )
            self._servers.append(srv)
            self._server_list.addItem(QListWidgetItem(srv.name))

        if self._servers:
            self._server_list.setCurrentRow(0)
        else:
            self._detail_stack.setCurrentIndex(0)

    def _sync_form_to_data(self):
        """将当前表单值同步回选中服务器的数据"""
        row = self._server_list.currentRow()
        if 0 <= row < len(self._servers):
            srv = self._servers[row]
            srv.name = self._name_edit.text().strip() or srv.name
            srv.mode = self._mode_combo.currentText()
            srv.host = self._host_edit.text().strip()
            srv.port = self._port_spin.value()
            srv.tcp_timeout = self._timeout_spin.value()
            srv.baudrate = int(self._baud_combo.currentText())
            srv.data_bits = int(self._databits_combo.currentText())
            srv.stop_bits = int(self._stopbits_combo.currentText())
            srv.parity = self._parity_combo.currentText()

    def save_to_dict(self) -> dict:
        """将当前页面设置导出为配置字典"""
        # 先同步当前选中的服务器
        self._sync_form_to_data()

        servers_list = []
        for srv in self._servers:
            servers_list.append(srv.to_dict())
        return {"servers": servers_list}

    def validate(self) -> list:
        """校验当前页面配置，返回错误信息列表"""
        self._sync_form_to_data()
        errors = []
        if not self._servers:
            errors.append("至少需要配置一台串口服务器")
        for i, srv in enumerate(self._servers):
            if not srv.host:
                errors.append(f"服务器 \"{srv.name}\" 的IP地址不能为空")
            if not srv.name:
                errors.append(f"第 {i+1} 台服务器名称不能为空")
        return errors

    def get_server_names(self) -> list:
        """返回所有服务器名称列表（供设备页使用）"""
        self._sync_form_to_data()
        return [srv.name for srv in self._servers]

    @property
    def server_count(self) -> int:
        return len(self._servers)
