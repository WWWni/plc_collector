"""
配置界面 — 从站设备管理页
=============================
支持多串口服务器：通过下拉框选择服务器，管理该服务器下的设备列表。
支持多设备类型：通过下拉框选择设备类型，每种类型有默认名称前缀。
设备列表的增删改、地址冲突校验，支持批量导入/导出与模板下载。
"""

import csv

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox, QMessageBox,
    QFileDialog, QAbstractItemView, QComboBox, QCheckBox,
)
from PySide6.QtCore import Qt

from gui.shared.styles import COLORS
from protocol.device_types import list_types, get_safe, get_default_name_prefix, get_default_type


def _csv_template() -> str:
    """根据注册表中的设备类型动态生成 CSV 模板"""
    header = "slave_addr,name,device_type,timeout,retry\n"
    types = list_types()
    if not types:
        return header + "1,设备1,,,,\n"
    lines = []
    addr = 1
    for type_key, display_name in types:
        prefix = get_default_name_prefix(type_key)
        lines.append(f"{addr},{prefix}{addr},{type_key},,\n")
        addr += 1
    return header + "".join(lines)


class RangeAddDialog(QDialog):
    """批量添加设备对话框"""

    def __init__(self, parent=None, existing_addrs=None):
        super().__init__(parent)
        self.setWindowTitle("批量添加设备")
        self.setMinimumWidth(420)
        self._existing_addrs = existing_addrs or set()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['bg_primary']};
            }}
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        # 设备类型选择
        self._type_combo = QComboBox()
        self._type_items = list_types()
        for type_key, display_name in self._type_items:
            self._type_combo.addItem(f"{display_name} ({type_key})", type_key)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("设备类型:", self._type_combo)

        self._start_spin = QSpinBox()
        self._start_spin.setRange(1, 128)
        self._start_spin.setValue(1)
        form.addRow("起始地址 (1-128):", self._start_spin)

        self._end_spin = QSpinBox()
        self._end_spin.setRange(1, 128)
        self._end_spin.setValue(10)
        form.addRow("结束地址 (1-128):", self._end_spin)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("留空则使用设备类型的默认前缀")
        form.addRow("设备名称前缀:", self._name_edit)

        hint = QLabel('最终设备名称 = 前缀 + 从站地址，如 "设备1"、"计米器1"')
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        form.addRow("", hint)

        layout.addLayout(form)

        self._preview_label = QLabel()
        self._preview_label.setObjectName("hintText")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            f"background-color: {COLORS['bg_input']}; "
            f"border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px; padding: 8px;"
        )
        layout.addWidget(self._preview_label)

        self._start_spin.valueChanged.connect(self._update_preview)
        self._end_spin.valueChanged.connect(self._update_preview)
        self._name_edit.textChanged.connect(self._update_preview)
        self._on_type_changed()  # 初始化默认前缀
        self._update_preview()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = QPushButton("确定添加")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def _on_type_changed(self):
        """设备类型变化时更新默认名称前缀"""
        type_key = self._type_combo.currentData()
        if type_key:
            default_prefix = get_default_name_prefix(type_key)
            self._name_edit.setPlaceholderText(f"默认: {default_prefix}")

    def _update_preview(self):
        start = self._start_spin.value()
        end = self._end_spin.value()
        type_key = self._type_combo.currentData() or get_default_type()
        prefix = self._name_edit.text().strip() or get_default_name_prefix(type_key)

        if start > end:
            self._preview_label.setText("起始地址不能大于结束地址")
            self._preview_label.setStyleSheet(
                f"background-color: {COLORS['bg_input']}; "
                f"border: 1px solid {COLORS['accent_red']}; "
                f"border-radius: 6px; padding: 8px; "
                f"color: {COLORS['accent_red']};"
            )
            return

        self._preview_label.setStyleSheet(
            f"background-color: {COLORS['bg_input']}; "
            f"border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px; padding: 8px;"
        )

        total = end - start + 1
        conflicts = [a for a in range(start, end + 1)
                     if a in self._existing_addrs]

        text = f"将新增 {total} 台设备: {prefix}{start} ~ {prefix}{end}"
        if conflicts:
            text += (f"\n其中 {len(conflicts)} 个地址已存在，将被跳过: "
                     f"{conflicts[:5]}{'...' if len(conflicts) > 5 else ''}")
        self._preview_label.setText(text)

    def get_values(self):
        type_key = self._type_combo.currentData() or get_default_type()
        prefix = self._name_edit.text().strip() or get_default_name_prefix(type_key)
        return (
            self._start_spin.value(),
            self._end_spin.value(),
            prefix,
            type_key,
        )


class DeviceEditDialog(QDialog):
    """设备编辑对话框（含设备类型选择）"""

    def __init__(self, parent=None, slave_addr=1, name="",
                 device_type="",
                 timeout=None, retry=None, title="添加设备"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['bg_primary']};
            }}
        """)

        import re
        # 编辑已有设备时，剥离名称末尾的数字，只显示前缀
        prefix = re.sub(r'\d+$', '', name) if name else ""

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        # 设备类型选择
        self._type_combo = QComboBox()
        self._type_items = list_types()
        for type_key, display_name in self._type_items:
            self._type_combo.addItem(f"{display_name} ({type_key})", type_key)
        # 设置当前类型
        for i, (type_key, _) in enumerate(self._type_items):
            if type_key == device_type:
                self._type_combo.setCurrentIndex(i)
                break
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("设备类型:", self._type_combo)

        self._addr_spin = QSpinBox()
        self._addr_spin.setRange(1, 128)
        self._addr_spin.setValue(slave_addr)
        form.addRow("从站地址 (1-128):", self._addr_spin)

        self._name_edit = QLineEdit(prefix)
        self._name_edit.setPlaceholderText("留空则使用设备类型的默认前缀")
        form.addRow("设备名称前缀:", self._name_edit)

        self._timeout_spin = QDoubleSpinBox()
        self._timeout_spin.setRange(0.0, 60.0)
        self._timeout_spin.setSingleStep(0.1)
        self._timeout_spin.setDecimals(1)
        self._timeout_spin.setSuffix(" 秒")
        self._timeout_spin.setSpecialValueText("默认")
        self._timeout_spin.setValue(timeout if timeout is not None else 0.0)
        form.addRow("通信超时 (可选):", self._timeout_spin)

        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(0, 20)
        self._retry_spin.setSpecialValueText("默认")
        self._retry_spin.setSuffix(" 次")
        self._retry_spin.setValue(retry if retry is not None else 0)
        form.addRow("重试次数 (可选):", self._retry_spin)

        hint = QLabel('最终设备名称 = 前缀 + 从站地址，如输入"设备"地址为1 → 设备1')
        hint.setObjectName("hintText")
        hint.setWordWrap(True)
        form.addRow("", hint)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def _on_type_changed(self):
        """设备类型变化时更新默认名称前缀提示"""
        type_key = self._type_combo.currentData()
        if type_key:
            default_prefix = get_default_name_prefix(type_key)
            self._name_edit.setPlaceholderText(f"默认: {default_prefix}")

    def get_values(self):
        timeout = self._timeout_spin.value()
        retry = self._retry_spin.value()
        type_key = self._type_combo.currentData() or get_default_type()
        # 名称 = 前缀 + 从站地址
        prefix = self._name_edit.text().strip() or get_default_name_prefix(type_key)
        full_name = f"{prefix}{self._addr_spin.value()}"
        return (
            self._addr_spin.value(),
            full_name,
            timeout if timeout > 0 else None,
            retry if retry > 0 else None,
            type_key,
        )


class DevicesPage(QWidget):
    """从站设备管理页（多服务器 + 多设备类型）"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._server_names: list[str] = []
        # 每台服务器一个设备列表: [[(addr, name, timeout, retry, device_type), ...], ...]
        self._devices_by_server: list[list] = []
        self._current_server_idx: int = 0
        self._checked_addrs: set = set()  # 当前选中的从站地址
        self._setup_ui()
        self._load_from_config()

    @property
    def _devices(self) -> list:
        """当前选中服务器的设备列表"""
        if 0 <= self._current_server_idx < len(self._devices_by_server):
            return self._devices_by_server[self._current_server_idx]
        return []

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(16)

        # 标题
        title = QLabel("设备管理")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel("管理各串口服务器下的从站设备列表，支持多设备类型")
        subtitle.setObjectName("hintText")
        layout.addWidget(subtitle)

        # ---- 服务器选择行 ----
        srv_row = QHBoxLayout()
        srv_label = QLabel("选择服务器:")
        srv_label.setStyleSheet(f"font-weight: bold; color: {COLORS['text_secondary']};")
        srv_row.addWidget(srv_label)

        self._server_combo = QComboBox()
        self._server_combo.setMinimumWidth(200)
        self._server_combo.currentIndexChanged.connect(self._on_server_changed)
        srv_row.addWidget(self._server_combo)
        srv_row.addStretch()
        layout.addLayout(srv_row)

        # ---- 操作按钮行1: 增删改 ----
        btn_row1 = QHBoxLayout()

        add_btn = QPushButton("+ 添加设备")
        add_btn.setObjectName("primaryBtn")
        add_btn.clicked.connect(self._add_device)
        btn_row1.addWidget(add_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit_device)
        btn_row1.addWidget(edit_btn)

        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_device)
        btn_row1.addWidget(del_btn)

        range_btn = QPushButton("批量添加")
        range_btn.clicked.connect(self._add_range_devices)
        btn_row1.addWidget(range_btn)

        self._select_all_btn = QPushButton("全选")
        self._select_all_btn.clicked.connect(self._toggle_select_all)
        btn_row1.addWidget(self._select_all_btn)

        batch_del_btn = QPushButton("批量删除")
        batch_del_btn.setStyleSheet(
            f"color: {COLORS.get('accent_red', '#f44336')}; font-weight: bold;")
        batch_del_btn.clicked.connect(self._batch_delete_devices)
        btn_row1.addWidget(batch_del_btn)

        btn_row1.addStretch()
        layout.addLayout(btn_row1)

        # ---- 操作按钮行2: 导入/导出/模板 ----
        btn_row2 = QHBoxLayout()

        tpl_btn = QPushButton("下载导入模板")
        tpl_btn.clicked.connect(self._download_template)
        btn_row2.addWidget(tpl_btn)

        import_btn = QPushButton("批量导入")
        import_btn.clicked.connect(self._import_devices)
        btn_row2.addWidget(import_btn)

        export_btn = QPushButton("导出设备")
        export_btn.clicked.connect(self._export_devices)
        btn_row2.addWidget(export_btn)

        btn_row2.addStretch()
        layout.addLayout(btn_row2)

        # ---- 设备表格 ----
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["", "从站地址", "设备类型", "设备名称", "超时(秒)", "重试(次)", "状态"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 36)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._edit_device)

        layout.addWidget(self._table)

        # 底部统计
        self._stats_label = QLabel()
        self._stats_label.setObjectName("hintText")
        layout.addWidget(self._stats_label)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_type_display_name(type_key: str) -> str:
        """获取设备类型的显示名称"""
        type_def = get_safe(type_key)
        return getattr(type_def, 'DISPLAY_NAME', type_key) if type_def else type_key

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _load_from_config(self):
        """从配置加载"""
        self._server_names = [srv.name for srv in self._config.servers]
        self._devices_by_server = []

        for srv in self._config.servers:
            devs = [
                (dev.slave_addr, dev.name, dev.timeout, dev.retry,
                 getattr(dev, 'device_type', ''))
                for dev in srv.devices
            ]
            self._devices_by_server.append(devs)

        # 填充下拉框
        self._server_combo.blockSignals(True)
        self._server_combo.clear()
        for name in self._server_names:
            self._server_combo.addItem(name)
        self._server_combo.blockSignals(False)

        if self._server_names:
            self._current_server_idx = 0
            self._server_combo.setCurrentIndex(0)
        self._refresh_table()

    def update_server_names(self, names: list):
        """由外部调用，当服务器名称变更时更新"""
        self._server_names = list(names)
        while len(self._devices_by_server) < len(names):
            self._devices_by_server.append([])
        if len(self._devices_by_server) > len(names):
            self._devices_by_server = self._devices_by_server[:len(names)]

        self._server_combo.blockSignals(True)
        self._server_combo.clear()
        for name in names:
            self._server_combo.addItem(name)
        if self._current_server_idx < len(names):
            self._server_combo.setCurrentIndex(self._current_server_idx)
        self._server_combo.blockSignals(False)
        self._refresh_table()

    def _on_server_changed(self, idx: int):
        if 0 <= idx < len(self._devices_by_server):
            self._current_server_idx = idx
            self._checked_addrs.clear()
            self._refresh_table()

    # ------------------------------------------------------------------
    # 表格刷新
    # ------------------------------------------------------------------

    def _refresh_table(self):
        """刷新表格显示"""
        devices = self._devices
        self._table.setRowCount(len(devices))
        for row, dev_tuple in enumerate(devices):
            addr, name, timeout, retry, device_type = dev_tuple

            # 勾选框
            cb = QCheckBox()
            cb.setChecked(addr in self._checked_addrs)
            cb.stateChanged.connect(
                lambda state, a=addr: self._on_checkbox_changed(a, state))
            self._table.setCellWidget(row, 0, cb)

            addr_item = QTableWidgetItem(str(addr))
            addr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 1, addr_item)

            type_item = QTableWidgetItem(self._get_type_display_name(device_type))
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, type_item)

            name_item = QTableWidgetItem(name or f"设备-{addr}")
            self._table.setItem(row, 3, name_item)

            timeout_item = QTableWidgetItem(
                f"{timeout}" if timeout is not None else "默认")
            timeout_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if timeout is None:
                timeout_item.setForeground(Qt.GlobalColor.gray)
            self._table.setItem(row, 4, timeout_item)

            retry_item = QTableWidgetItem(
                str(retry) if retry is not None else "默认")
            retry_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if retry is None:
                retry_item.setForeground(Qt.GlobalColor.gray)
            self._table.setItem(row, 5, retry_item)

            status_item = QTableWidgetItem("就绪")
            status_item.setForeground(Qt.GlobalColor.green)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 6, status_item)

        # 同步全选按钮文字
        all_addrs = {d[0] for d in devices}
        if all_addrs and all_addrs.issubset(self._checked_addrs):
            self._select_all_btn.setText("取消全选")
        else:
            self._select_all_btn.setText("全选")

        srv_name = (
            self._server_names[self._current_server_idx]
            if 0 <= self._current_server_idx < len(self._server_names)
            else "?"
        )
        addr_list = [d[0] for d in devices]
        type_counts = {}
        for d in devices:
            t = d[4]
            type_counts[self._get_type_display_name(t)] = type_counts.get(self._get_type_display_name(t), 0) + 1
        type_summary = ", ".join(f"{k}:{v}" for k, v in type_counts.items())
        self._stats_label.setText(
            f"[{srv_name}] 共 {len(devices)} 台设备 "
            f"({type_summary})，"
            f"地址范围: "
            f"{min(addr_list) if addr_list else '-'} ~ "
            f"{max(addr_list) if addr_list else '-'}"
        )

    def _on_checkbox_changed(self, addr: int, state):
        """勾选框状态变化回调"""
        if state == Qt.CheckState.Checked.value:
            self._checked_addrs.add(addr)
        else:
            self._checked_addrs.discard(addr)
        all_addrs = {d[0] for d in self._devices}
        if all_addrs and all_addrs.issubset(self._checked_addrs):
            self._select_all_btn.setText("取消全选")
        else:
            self._select_all_btn.setText("全选")

    # ------------------------------------------------------------------
    # 设备增删改
    # ------------------------------------------------------------------

    def _add_device(self):
        used_addrs = {d[0] for d in self._devices}
        suggested = 1
        for i in range(1, 129):
            if i not in used_addrs:
                suggested = i
                break

        dlg = DeviceEditDialog(self, slave_addr=suggested, title="添加设备")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            addr, name, timeout, retry, device_type = dlg.get_values()
            if any(d[0] == addr for d in self._devices):
                QMessageBox.warning(
                    self, "地址冲突",
                    f"从站地址 {addr} 已被使用。"
                )
                return
            self._devices.append((addr, name, timeout, retry, device_type))
            self._devices.sort(key=lambda x: x[0])
            self._refresh_table()

    def _add_range_devices(self):
        used_addrs = {d[0] for d in self._devices}
        dlg = RangeAddDialog(self, existing_addrs=used_addrs)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            start, end, prefix, device_type = dlg.get_values()
            if start > end:
                QMessageBox.warning(self, "参数错误", "起始地址不能大于结束地址。")
                return
            added = 0
            skipped = 0
            for addr in range(start, end + 1):
                if addr in used_addrs:
                    skipped += 1
                    continue
                self._devices.append((addr, f"{prefix}{addr}", None, None, device_type))
                added += 1
            self._devices.sort(key=lambda x: x[0])
            self._refresh_table()
            msg = f"成功添加 {added} 台设备。"
            if skipped:
                msg += f"\n跳过 {skipped} 个已存在的地址。"
            QMessageBox.information(self, "批量添加完成", msg)

    def _edit_device(self):
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要编辑的设备")
            return
        old_addr, old_name, old_timeout, old_retry, old_type = self._devices[row]
        dlg = DeviceEditDialog(
            self, slave_addr=old_addr, name=old_name,
            device_type=old_type,
            timeout=old_timeout, retry=old_retry, title="编辑设备"
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_addr, new_name, new_timeout, new_retry, new_type = dlg.get_values()
            if new_addr != old_addr and any(
                d[0] == new_addr for d in self._devices
            ):
                QMessageBox.warning(self, "地址冲突", f"从站地址 {new_addr} 已被使用。")
                return
            self._devices[row] = (new_addr, new_name, new_timeout, new_retry, new_type)
            self._devices.sort(key=lambda x: x[0])
            self._refresh_table()

    def _delete_device(self):
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要删除的设备")
            return
        addr, name, *_ = self._devices[row]
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除设备 \"{name or f'设备-{addr}'}\" (地址={addr}) 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._devices.pop(row)
            self._checked_addrs.discard(addr)
            self._refresh_table()

    def _toggle_select_all(self):
        """全选 / 取消全选"""
        all_addrs = {d[0] for d in self._devices}
        if all_addrs and all_addrs.issubset(self._checked_addrs):
            self._checked_addrs.clear()
        else:
            self._checked_addrs = all_addrs
        self._refresh_table()

    def _batch_delete_devices(self):
        """批量删除已勾选的设备"""
        if not self._checked_addrs:
            QMessageBox.information(self, "提示", "请先勾选要删除的设备")
            return
        to_delete = [d for d in self._devices if d[0] in self._checked_addrs]
        count = len(to_delete)
        reply = QMessageBox.question(
            self, "确认批量删除",
            f"确定要删除已勾选的 {count} 台设备吗？\n\n"
            f"涉及地址: {sorted(self._checked_addrs)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._devices[:] = [d for d in self._devices
                                if d[0] not in self._checked_addrs]
            self._checked_addrs.clear()
            self._refresh_table()
            QMessageBox.information(self, "批量删除完成",
                                    f"已删除 {count} 台设备。")

    # ------------------------------------------------------------------
    # 模板下载 / 批量导入 / 导出
    # ------------------------------------------------------------------

    def _download_template(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存导入模板", "设备导入模板.csv",
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            if not path.lower().endswith(".csv"):
                path += ".csv"
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(_csv_template())

            # 构建可用类型说明
            type_lines = []
            for type_key, display_name in list_types():
                type_lines.append(f"  - {type_key}: {display_name}")

            QMessageBox.information(
                self, "模板已保存",
                f"导入模板已保存到:\n{path}\n\n"
                f"模板说明:\n"
                f"  - slave_addr: 从站地址 (必填, 1-128)\n"
                f"  - name: 设备名称 (必填)\n"
                f"  - device_type: 设备类型 (可选, 留空使用默认类型)\n"
                f"  - timeout: 通信超时秒数 (可选)\n"
                f"  - retry: 重试次数 (可选)\n\n"
                f"可用设备类型:\n" + "\n".join(type_lines),
            )
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _import_devices(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入设备列表", "",
            "CSV 文件 (*.csv);;文本文件 (*.txt);;所有文件 (*)",
        )
        if not path:
            return
        try:
            imported = 0
            skipped = []
            used_addrs = {d[0] for d in self._devices}

            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row or (len(row) == 1 and not row[0].strip()):
                        continue
                    first = row[0].strip().lower()
                    if first in ("slave_addr", "地址", "从站地址", "#"):
                        continue
                    if first.startswith("#"):
                        continue
                    addr_str = row[0].strip()
                    if not addr_str:
                        continue
                    try:
                        addr = int(addr_str)
                    except ValueError:
                        skipped.append(f"行 {row}: 地址非数字")
                        continue
                    name = row[1].strip() if len(row) >= 2 and row[1].strip() else f"设备-{addr}"
                    device_type = row[2].strip() if len(row) >= 3 and row[2].strip() else ""
                    timeout = None
                    retry = None
                    if len(row) >= 4 and row[3].strip():
                        try:
                            timeout = float(row[3].strip())
                        except ValueError:
                            pass
                    if len(row) >= 5 and row[4].strip():
                        try:
                            retry = int(float(row[4].strip()))
                        except ValueError:
                            pass
                    if not (1 <= addr <= 128):
                        skipped.append(f"地址 {addr} 超出范围(1-128)")
                        continue
                    if addr in used_addrs:
                        skipped.append(f"地址 {addr} 已存在")
                        continue
                    self._devices.append((addr, name, timeout, retry, device_type))
                    used_addrs.add(addr)
                    imported += 1

            self._devices.sort(key=lambda x: x[0])
            self._refresh_table()

            msg = f"成功导入 {imported} 台设备。"
            if skipped:
                msg += f"\n\n跳过 {len(skipped)} 条:\n" + "\n".join(
                    f"  - {s}" for s in skipped[:10]
                )
                if len(skipped) > 10:
                    msg += f"\n  ... 等共 {len(skipped)} 条"
            QMessageBox.information(self, "导入完成", msg)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _export_devices(self):
        if not self._devices:
            QMessageBox.information(self, "提示", "当前服务器下没有设备可导出")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出设备列表", "设备列表.csv",
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            if not path.lower().endswith(".csv"):
                path += ".csv"
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["slave_addr", "name", "device_type", "timeout", "retry"])
                for addr, name, timeout, retry, device_type in self._devices:
                    writer.writerow([
                        addr, name, device_type,
                        timeout if timeout is not None else "",
                        retry if retry is not None else "",
                    ])
            QMessageBox.information(
                self, "导出成功",
                f"已导出 {len(self._devices)} 台设备到:\n{path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    # ------------------------------------------------------------------
    # 保存/校验
    # ------------------------------------------------------------------

    def save_to_dict(self) -> dict:
        """
        返回各服务器的设备列表（按索引对应）。
        main_window 负责将 servers_page 的连接参数与此合并。
        """
        servers_devices = []
        for devs in self._devices_by_server:
            devices_list = []
            for addr, name, timeout, retry, device_type in devs:
                d = {
                    "slave_addr": addr,
                    "name": name,
                    "device_type": device_type,
                }
                if timeout is not None:
                    d["timeout"] = timeout
                if retry is not None:
                    d["retry"] = retry
                devices_list.append(d)
            servers_devices.append(devices_list)
        return {"_servers_devices": servers_devices}

    def validate(self) -> list:
        errors = []
        total = sum(len(d) for d in self._devices_by_server)
        if total == 0:
            errors.append("至少需要配置一台设备")

        # 校验可用设备类型
        valid_types = {t[0] for t in list_types()}

        for idx, devs in enumerate(self._devices_by_server):
            srv_name = (
                self._server_names[idx]
                if idx < len(self._server_names)
                else f"服务器{idx}"
            )
            addrs = [d[0] for d in devs]
            if len(addrs) != len(set(addrs)):
                errors.append(f"[{srv_name}] 存在重复的从站地址")
            for addr, name, timeout, retry, device_type in devs:
                if not 1 <= addr <= 128:
                    errors.append(
                        f"[{srv_name}] 从站地址 {addr} 超出有效范围(1-128)"
                    )
                if device_type not in valid_types:
                    errors.append(
                        f"[{srv_name}] 设备 {name} 使用了未知类型: {device_type}"
                    )
        return errors
