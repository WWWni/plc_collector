"""
故障告警日志 Tab
================
上方: 当前活跃故障列表（红色高亮）
下方: 历史故障记录表格 + 筛选 + 导出
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QComboBox,
    QPushButton, QFileDialog, QSplitter, QFrame,
    QScroller, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from datetime import datetime
from typing import Dict, List, Any

from gui.shared.styles import COLORS

# 历史记录最大保留条数
MAX_HISTORY_RECORDS = 200


class FaultRecord:
    """一条故障记录"""
    def __init__(self, device_name: str, slave_addr: int,
                 fault_name: str, start_time: datetime):
        self.device_name = device_name
        self.slave_addr = slave_addr
        self.fault_name = fault_name
        self.start_time = start_time
        self.end_time = None

    @property
    def duration_str(self) -> str:
        if self.end_time:
            delta = self.end_time - self.start_time
            mins, secs = divmod(int(delta.total_seconds()), 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                return f"{hours}h {mins}m {secs}s"
            elif mins > 0:
                return f"{mins}m {secs}s"
            return f"{secs}s"
        return "持续中"

    @property
    def is_active(self) -> bool:
        return self.end_time is None


class AlarmsTab(QWidget):
    """故障告警Tab"""

    _history_loaded_signal = Signal(list)  # 后台线程加载完成后发送事件列表

    def __init__(self, db_manager=None, parent=None):
        super().__init__(parent)
        self._db_manager = db_manager
        # 跟踪每台设备的当前故障状态
        self._last_faults: Dict[int, set] = {}  # slave_addr -> set of fault names
        self._active_records: Dict[str, FaultRecord] = {}  # key="addr:fault_name"
        self._all_records: List[FaultRecord] = []

        # 连接信号：后台线程加载完数据后刷新 UI
        self._history_loaded_signal.connect(self._on_history_loaded)

        self._setup_ui()

    def set_db_manager(self, db_manager):
        """设置数据库管理器（不触发加载）"""
        self._db_manager = db_manager

    def load_from_db_async(self):
        """在后台线程加载历史故障数据，不阻塞 UI"""
        self._loading_label.show()
        self._history_table.hide()
        import threading
        t = threading.Thread(target=self._do_load_from_db, daemon=True)
        t.start()

    def _do_load_from_db(self):
        """后台线程：查询数据库获取故障事件列表"""
        if not self._db_manager:
            return
        try:
            events = self._db_manager.query_fault_events(limit=200)
            # 通过信号将数据传递到主线程处理
            self._history_loaded_signal.emit(events)
        except Exception as e:
            import logging
            logging.getLogger("plc_collector.alarms").warning(
                f"从数据库加载故障记录失败: {e}"
            )

    def _on_history_loaded(self, events: list):
        """主线程：处理加载完成的事件数据并刷新 UI"""
        self._loading_label.hide()
        self._history_table.show()
        self._all_records.clear()
        self._active_records.clear()

        for ev in events:
            device_name = ev.get("device_name", "")
            slave_addr = ev.get("slave_addr", 0)
            fault_name = ev.get("fault_name", "")
            start_str = ev.get("start_time", "")
            end_str = ev.get("end_time")

            try:
                start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue

            rec = FaultRecord(device_name, slave_addr, fault_name, start_time)
            if end_str:
                try:
                    rec.end_time = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    pass

            key = f"{slave_addr}:{fault_name}"
            if rec.end_time is None:
                self._active_records[key] = rec
                self._last_faults.setdefault(slave_addr, set()).add(fault_name)
            else:
                self._all_records.append(rec)

            if self._device_filter.findData(slave_addr) == -1:
                self._device_filter.addItem(device_name, slave_addr)

        if len(self._all_records) > MAX_HISTORY_RECORDS:
            self._all_records = self._all_records[:MAX_HISTORY_RECORDS]

        self._refresh_active_table()
        self._refresh_history_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ---- 上方: 当前活跃故障 ----
        active_group = QGroupBox("当前活跃故障")
        active_layout = QVBoxLayout(active_group)

        self._active_table = QTableWidget()
        self._active_table.setColumnCount(4)
        self._active_table.setHorizontalHeaderLabels(
            ["设备", "地址", "故障类型", "发生时间"]
        )
        self._active_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._active_table.setAlternatingRowColors(True)
        self._active_table.verticalHeader().setVisible(False)
        self._active_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        # 触屏滑动支持
        self._active_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        QScroller.grabGesture(
            self._active_table.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        active_layout.addWidget(self._active_table)

        self._no_fault_label = QLabel("✓ 当前无故障")
        self._no_fault_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_fault_label.setStyleSheet(
            f"color: {COLORS['accent_green']}; font-size: 16px; "
            f"font-weight: bold; padding: 20px;"
        )
        active_layout.addWidget(self._no_fault_label)

        layout.addWidget(active_group)

        # ---- 筛选栏 ----
        filter_bar = QHBoxLayout()

        filter_bar.addWidget(QLabel("筛选设备:"))
        self._device_filter = QComboBox()
        self._device_filter.addItem("全部设备", 0)
        self._device_filter.setMinimumWidth(150)
        self._device_filter.currentIndexChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._device_filter)

        filter_bar.addStretch()

        export_btn = QPushButton("导出CSV")
        export_btn.clicked.connect(self._export_csv)
        filter_bar.addWidget(export_btn)

        layout.addLayout(filter_bar)

        # ---- 下方: 历史故障表格 ----
        self._history_table = QTableWidget()
        self._history_table.setColumnCount(6)
        self._history_table.setHorizontalHeaderLabels(
            ["设备", "地址", "故障类型", "发生时间", "恢复时间", "持续时长"]
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._history_table.setAlternatingRowColors(True)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        # 触屏滑动支持
        self._history_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        QScroller.grabGesture(
            self._history_table.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        layout.addWidget(self._history_table)

        # 加载中提示（覆盖在历史表格上方，初始隐藏）
        self._loading_label = QLabel("⏳ 正在加载历史告警数据...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet(
            f"color: {COLORS['accent_yellow']}; font-size: 14px; "
            f"font-weight: bold; padding: 40px;"
        )
        self._loading_label.hide()
        layout.addWidget(self._loading_label)

        # 初始隐藏表格，显示无故障
        self._no_fault_label.show()
        self._active_table.hide()

    def check_faults(self, data_list: List[dict]):
        """
        检查故障变化（由MonitorMainWindow调用）

        通过对比前后两轮的故障位，检测新增和恢复的故障。
        """
        for data in data_list:
            addr = data.get("slave_addr", 0)
            name = data.get("device_name", f"设备-{addr}")
            faults = set(data.get("active_faults", []))

            # 添加到设备筛选下拉
            if self._device_filter.findData(addr) == -1:
                self._device_filter.addItem(name, addr)

            prev_faults = self._last_faults.get(addr, set())

            # 新增故障
            new_faults = faults - prev_faults
            for fault in new_faults:
                record = FaultRecord(name, addr, fault, datetime.now())
                key = f"{addr}:{fault}"
                self._active_records[key] = record

            # 恢复的故障
            recovered = prev_faults - faults
            for fault in recovered:
                key = f"{addr}:{fault}"
                if key in self._active_records:
                    record = self._active_records.pop(key)
                    record.end_time = datetime.now()
                    self._all_records.insert(0, record)

            self._last_faults[addr] = faults

        # 截断历史记录，防止内存无限增长
        if len(self._all_records) > MAX_HISTORY_RECORDS:
            self._all_records = self._all_records[:MAX_HISTORY_RECORDS]

        self._refresh_active_table()
        self._refresh_history_table()

    def _refresh_active_table(self):
        """刷新活跃故障表格"""
        records = list(self._active_records.values())

        if not records:
            self._active_table.hide()
            self._no_fault_label.show()
            return

        self._no_fault_label.hide()
        self._active_table.show()
        self._active_table.setRowCount(len(records))

        for row, rec in enumerate(records):
            items = [
                rec.device_name,
                str(rec.slave_addr),
                rec.fault_name,
                rec.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(COLORS['accent_red']))
                self._active_table.setItem(row, col, item)

    def _refresh_history_table(self):
        """刷新历史故障表格"""
        # 合并活跃记录和已完成记录
        all_recs = (
            list(self._active_records.values()) + self._all_records
        )

        self._history_table.setRowCount(len(all_recs))

        for row, rec in enumerate(all_recs):
            items = [
                rec.device_name,
                str(rec.slave_addr),
                rec.fault_name,
                rec.start_time.strftime("%H:%M:%S"),
                (rec.end_time.strftime("%H:%M:%S") if rec.end_time else "—"),
                rec.duration_str,
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                if rec.is_active:
                    item.setForeground(QColor(COLORS['accent_red']))
                self._history_table.setItem(row, col, item)

    def _apply_filter(self):
        """按设备筛选历史表格"""
        addr = self._device_filter.currentData()
        for row in range(self._history_table.rowCount()):
            if addr == 0:
                self._history_table.showRow(row)
            else:
                cell = self._history_table.item(row, 1)
                self._history_table.setRowHidden(
                    row, cell.text() != str(addr) if cell else True
                )

    def _export_csv(self):
        """导出故障记录为CSV"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出故障记录", "fault_log.csv", "CSV文件 (*.csv)"
        )
        if not path:
            return

        import csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["设备", "地址", "故障类型", "发生时间", "恢复时间", "持续时长"]
            )
            for row in range(self._history_table.rowCount()):
                writer.writerow([
                    self._history_table.item(row, col).text()
                    for col in range(6)
                ])
