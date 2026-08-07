"""PySide6 GUI for browsing For The King II save files."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ftk2_editor import (
    FTK2_GAME_DIR,
    backup,
    carry_over_consumables,
    decrypt_ftk2_bytes,
    ensure_character_herb_tool_minimum,
    set_character_gold,
)
from ftk2_editor.viewmodel import (
    find_carryover_source,
    list_save_candidates,
    load_save_view,
    run_display_name,
)

APP_TITLE = "FTK2 Save Reader"
MAX_TREE_CHILDREN = 200
MAX_TREE_DEPTH = 6
GOLD_PRESETS = (0, 100, 500, 1_000, 5_000, 9_999, 99_999)


class LoadWorker(QThread):
    """Parse a save file on a background thread."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            self.finished_ok.emit(load_save_view(self.path))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 740)

        self._view: dict[str, Any] | None = None
        self._path: Path | None = None
        self._party_rows: list[dict[str, Any]] = []
        self._non_party_rows: list[dict[str, Any]] = []
        self._worker: LoadWorker | None = None
        self._load_generation = 0
        self._sidebar_paths: list[Path] = []
        self._pending_select_guid: str | None = None
        self._pending_focus_inventory = False
        self._inventory_windows: list[QDialog] = []

        self._build_actions()
        self._build_ui()
        self.refresh_sidebar()
        self.statusBar().showMessage("Open User.ftk2 or a GameRuns save to begin.")

    def _build_actions(self) -> None:
        open_act = QAction("Open…", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self.open_file_dialog)

        user_act = QAction("Open User.ftk2", self)
        user_act.triggered.connect(self.open_user_save)

        refresh_act = QAction("Refresh list", self)
        refresh_act.triggered.connect(self.refresh_sidebar)

        export_act = QAction("Export decrypted JSON…", self)
        export_act.triggered.connect(self.export_json)

        quit_act = QAction("Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(open_act)
        file_menu.addAction(user_act)
        file_menu.addAction(refresh_act)
        file_menu.addSeparator()
        file_menu.addAction(export_act)
        file_menu.addSeparator()
        file_menu.addAction(quit_act)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(open_act)
        toolbar.addAction(user_act)
        toolbar.addAction(refresh_act)
        toolbar.addAction(export_act)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Saves"))
        path_hint = QLabel(str(FTK2_GAME_DIR))
        path_hint.setWordWrap(True)
        path_hint.setStyleSheet("color: #9aa3ad;")
        left_layout.addWidget(path_hint)
        self.save_list = QListWidget()
        # itemClicked avoids loads from clear()/programmatic selection changes
        self.save_list.itemClicked.connect(self._on_sidebar_item_clicked)
        left_layout.addWidget(self.save_list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.path_label = QLabel("No file loaded")
        self.path_label.setStyleSheet("color: #9aa3ad;")
        right_layout.addWidget(self.path_label)

        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)

        self.overview = QTextEdit()
        self.overview.setReadOnly(True)
        self.overview.setFont(QFont("Consolas", 11))
        self.tabs.addTab(self.overview, "Overview")

        self.party_table = QTableWidget(0, 7)
        self.party_table.setHorizontalHeaderLabels(
            ["Name", "Class", "HP", "Focus", "Gold", "XP", "Map"]
        )
        self.party_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.party_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.party_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.party_table.horizontalHeader().setStretchLastSection(True)
        self.party_table.setSortingEnabled(True)
        self.party_table.itemSelectionChanged.connect(self._on_party_select)
        self.party_table.cellDoubleClicked.connect(self._on_party_double_click)

        party_wrap = QWidget()
        party_layout = QVBoxLayout(party_wrap)
        party_layout.setContentsMargins(0, 0, 0, 0)
        party_layout.addWidget(self.party_table)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("Selected gold"))
        self.gold_spin = QSpinBox()
        self.gold_spin.setRange(0, 999_999_999)
        self.gold_spin.setSingleStep(100)
        self.gold_spin.setEnabled(False)
        edit_row.addWidget(self.gold_spin)

        self._gold_preset_buttons: list[QPushButton] = []
        for amount in GOLD_PRESETS:
            label = f"{amount:,}"
            btn = QPushButton(label)
            btn.setEnabled(False)
            btn.setToolTip(f"Set gold field to {amount:,}")
            btn.clicked.connect(lambda _checked=False, value=amount: self.gold_spin.setValue(value))
            self._gold_preset_buttons.append(btn)
            edit_row.addWidget(btn)

        self.apply_gold_btn = QPushButton("Apply & save to file")
        self.apply_gold_btn.setEnabled(False)
        self.apply_gold_btn.clicked.connect(self.apply_selected_gold)
        edit_row.addWidget(self.apply_gold_btn)
        self.apply_all_gold_btn = QPushButton("Apply to all party")
        self.apply_all_gold_btn.setEnabled(False)
        self.apply_all_gold_btn.setToolTip("Set every party member’s wallet to the selected gold amount")
        self.apply_all_gold_btn.clicked.connect(self.apply_gold_to_all_party)
        edit_row.addWidget(self.apply_all_gold_btn)
        edit_row.addStretch(1)
        self.gold_hint = QLabel("Open a GameRuns/*.ftk2 save, select a character, set gold.")
        self.gold_hint.setStyleSheet("color: #9aa3ad;")
        edit_row.addWidget(self.gold_hint)
        party_layout.addLayout(edit_row)
        self.tabs.addTab(party_wrap, "Party")

        npc_wrap = QWidget()
        npc_layout = QVBoxLayout(npc_wrap)
        self.npc_label = QLabel("Non-party character entities in this run")
        self.npc_label.setStyleSheet("color: #9aa3ad;")
        npc_layout.addWidget(self.npc_label)
        self.npc_table = QTableWidget(0, 7)
        self.npc_table.setHorizontalHeaderLabels(
            ["Name", "Class", "HP", "Focus", "Gold", "XP", "Map"]
        )
        self.npc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.npc_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.npc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.npc_table.horizontalHeader().setStretchLastSection(True)
        self.npc_table.setSortingEnabled(True)
        self.npc_table.cellDoubleClicked.connect(self._on_npc_double_click)
        npc_layout.addWidget(self.npc_table)
        self.tabs.addTab(npc_wrap, "Non-Party")

        self.inventory_tab = QWidget()
        inv_layout = QVBoxLayout(self.inventory_tab)
        self.inventory_label = QLabel("Select a party member")
        self.inventory_label.setStyleSheet("color: #9aa3ad;")
        inv_layout.addWidget(self.inventory_label)
        inv_action_row = QHBoxLayout()
        self.topup_herb_tool_btn = QPushButton("Set herbs/tools/drinks/scrolls/safetystones to min 10")
        self.topup_herb_tool_btn.setEnabled(False)
        self.topup_herb_tool_btn.setToolTip(
            "For selected character, set every herb/tool/drink/scroll/safetystone stack below 10 up to 10"
        )
        self.topup_herb_tool_btn.clicked.connect(self.apply_inventory_herb_tool_topup)
        inv_action_row.addWidget(self.topup_herb_tool_btn)
        self.carry_over_btn = QPushButton("Carry over consumables from last act")
        self.carry_over_btn.setEnabled(False)
        self.carry_over_btn.setToolTip(
            "Add the herbs/drinks/tools/scrolls/safetystones from the previous act's most recent save onto this party"
        )
        self.carry_over_btn.clicked.connect(self.apply_carry_over_consumables)
        inv_action_row.addWidget(self.carry_over_btn)
        inv_action_row.addStretch(1)
        inv_layout.addLayout(inv_action_row)
        self.inventory_table = QTableWidget(0, 3)
        self.inventory_table.setHorizontalHeaderLabels(["Type", "Item", "Qty"])
        self.inventory_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.inventory_table.horizontalHeader().setStretchLastSection(True)
        self.inventory_table.setSortingEnabled(True)
        inv_layout.addWidget(self.inventory_table)
        self.tabs.addTab(self.inventory_tab, "Inventory")

        stats_wrap = QWidget()
        stats_layout = QVBoxLayout(stats_wrap)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter"))
        self.stats_filter = QLineEdit()
        self.stats_filter.setPlaceholderText("gold, lore, …")
        self.stats_filter.textChanged.connect(self._populate_stats)
        filter_row.addWidget(self.stats_filter)
        stats_layout.addLayout(filter_row)
        self.stats_table = QTableWidget(0, 2)
        self.stats_table.setHorizontalHeaderLabels(["Stat", "Value"])
        self.stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.setSortingEnabled(True)
        stats_layout.addWidget(self.stats_table)
        self.tabs.addTab(stats_wrap, "Stats")

        self.json_tree = QTreeWidget()
        self.json_tree.setHeaderLabels(["Key", "Value"])
        self.json_tree.header().setStretchLastSection(True)
        self.tabs.addTab(self.json_tree, "JSON")

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])

        self.setStatusBar(QStatusBar())
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #1c1f24; color: #e8eaed; }
            QListWidget, QTextEdit, QTableWidget, QTreeWidget, QLineEdit {
                background: #15181d; color: #e8eaed; border: 1px solid #2a2f38;
            }
            QHeaderView::section { background: #2a2f38; color: #e8eaed; padding: 4px; }
            QTabBar::tab { background: #2a2f38; color: #c5c9d0; padding: 8px 14px; }
            QTabBar::tab:selected { background: #3a4554; color: #ffffff; }
            QToolBar { background: #15181d; border: none; spacing: 6px; }
            QStatusBar { background: #12151a; color: #9aa3ad; }
            QMenuBar { background: #15181d; color: #e8eaed; }
            QMenu { background: #1c1f24; color: #e8eaed; }
            QPushButton, QSpinBox {
                background: #2f3640; color: #e8eaed; border: 1px solid #3d4654; padding: 4px 10px;
            }
            QPushButton:disabled, QSpinBox:disabled { color: #6b7280; }
            """
        )

    def refresh_sidebar(self) -> None:
        self.save_list.clear()
        self._sidebar_paths = []
        for item in list_save_candidates():
            path: Path = item["path"]
            mtime = datetime.fromtimestamp(item["mtime"]).strftime("%Y-%m-%d %H:%M")
            size_mb = path.stat().st_size / (1024 * 1024)
            label = f"{item['label']}  ·  {mtime}  ·  {size_mb:.1f} MB"
            self.save_list.addItem(QListWidgetItem(label))
            self._sidebar_paths.append(path)
        self.statusBar().showMessage(f"Found {len(self._sidebar_paths)} save(s).")

    def _on_sidebar_item_clicked(self, item: QListWidgetItem) -> None:
        row = self.save_list.row(item)
        if row < 0 or row >= len(self._sidebar_paths):
            return
        self.load_path(self._sidebar_paths[row])

    def open_user_save(self) -> None:
        user = FTK2_GAME_DIR / "User.ftk2"
        if not user.exists():
            QMessageBox.critical(self, APP_TITLE, f"User.ftk2 not found:\n{user}")
            return
        self.load_path(user)

    def open_file_dialog(self) -> None:
        initial = str(FTK2_GAME_DIR if FTK2_GAME_DIR.exists() else Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open FTK2 save",
            initial,
            "FTK2 saves (*.ftk2);;All files (*)",
        )
        if path:
            self.load_path(Path(path))

    def _stop_loader(self) -> None:
        """Wait for any in-flight load (QThread.run returns → thread finished)."""
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        if worker.isRunning():
            # Do not call quit()/terminate for a QThread subclass that only
            # overrides run() — wait until parsing finishes.
            worker.wait()
        worker.deleteLater()

    def load_path(self, path: Path) -> None:
        self._load_generation += 1
        generation = self._load_generation
        self._stop_loader()

        self._path = Path(path)
        self.path_label.setText(str(path))
        self.statusBar().showMessage(f"Loading {path.name}…")

        worker = LoadWorker(self._path, self)
        worker.finished_ok.connect(lambda view, g=generation: self._on_loaded(g, view))
        worker.failed.connect(lambda message, g=generation: self._on_load_failed(g, message))
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_load_failed(self, generation: int, message: str) -> None:
        if generation != self._load_generation:
            return
        if self._worker is not None and not self._worker.isRunning():
            self._worker = None
        QMessageBox.critical(self, APP_TITLE, f"Failed to load save:\n{message}")
        self.statusBar().showMessage("Load failed")

    def _on_loaded(self, generation: int, view: dict[str, Any]) -> None:
        if generation != self._load_generation:
            return
        if self._worker is not None and not self._worker.isRunning():
            self._worker = None
        self._view = view
        self._party_rows = list(view.get("party") or [])
        self._non_party_rows = list(view.get("non_party") or [])
        self._populate_overview()
        self._populate_party()
        self._populate_non_party()
        selected = False
        pending_guid = self._pending_select_guid
        if pending_guid:
            selected = self._reselect_party_by_guid(pending_guid)
            self._pending_select_guid = None
        if not selected:
            self._populate_inventory(None)
            self._set_inventory_controls_enabled(False)
        if selected and self._pending_focus_inventory:
            self.tabs.setCurrentWidget(self.inventory_tab)
        self._pending_focus_inventory = False
        self._populate_stats()
        self._populate_json_tree()
        gold_total = view["overview"].get("party_gold_total")
        extra = f" · party gold {gold_total}" if gold_total is not None else ""
        name = Path(view["path"]).name if view.get("path") else ""
        self.statusBar().showMessage(f"Loaded {name} ({view['kind']}){extra}")

    def _reselect_party_by_guid(self, guid: str) -> bool:
        for row_idx in range(self.party_table.rowCount()):
            item = self.party_table.item(row_idx, 0)
            if item is None:
                continue
            row = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(row, dict) and row.get("guid") == guid:
                self.party_table.selectRow(row_idx)
                return True
        return False

    def _row_for_table(self, table: QTableWidget, visual_row: int) -> dict[str, Any] | None:
        if visual_row < 0:
            return None
        item = table.item(visual_row, 0)
        if item is None:
            return None
        row = item.data(Qt.ItemDataRole.UserRole)
        return row if isinstance(row, dict) else None

    def _open_inventory_window(self, row: dict[str, Any], *, title_prefix: str) -> None:
        inventory = row.get("inventory") or []
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"{title_prefix}: {row.get('name')}")
        dialog.resize(720, 420)

        layout = QVBoxLayout(dialog)
        gold = row.get("gold")
        info = QLabel(
            f"{row.get('name')} · {row.get('class')} · gold={gold if gold is not None else '—'}"
        )
        info.setStyleSheet("color: #9aa3ad;")
        layout.addWidget(info)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Type", "Item", "Qty"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(False)
        table.setRowCount(len(inventory))
        for i, entry in enumerate(inventory):
            table.setItem(i, 0, QTableWidgetItem(str(entry.get("type") or "")))
            table.setItem(i, 1, QTableWidgetItem(str(entry.get("config") or "")))
            table.setItem(i, 2, QTableWidgetItem(str(entry.get("count"))))
        table.setSortingEnabled(True)
        layout.addWidget(table)

        self._inventory_windows.append(dialog)
        dialog.finished.connect(lambda _code: self._inventory_windows.remove(dialog) if dialog in self._inventory_windows else None)
        dialog.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._load_generation += 1  # ignore late UI updates
        self._stop_loader()
        super().closeEvent(event)

    def _populate_overview(self) -> None:
        assert self._view is not None
        o = self._view["overview"]
        lines = [
            str(o.get("title") or "Save"),
            "",
            f"Path: {o.get('path')}",
            f"Kind: {o.get('kind')}",
            f"File size: {o.get('file_size')} bytes",
            f"Plaintext size: {o.get('plaintext_size')} bytes",
        ]
        if o.get("parse_error"):
            lines.append(f"Parse note: {o['parse_error']}")
        lines.append("")
        if o.get("kind") == "user":
            lines.extend(
                [
                    f"Version: {o.get('version')}",
                    f"Difficulty: {o.get('difficulty')}",
                    f"Language: {o.get('language')}",
                    f"Last run: {o.get('last_run')}",
                    f"TOTAL_LORE: {o.get('lore')}",
                    f"GOLD_COLLECTED (lifetime): {o.get('gold_collected')}",
                    f"GOLD_SPENT (lifetime): {o.get('gold_spent')}",
                    f"Lore store unlocks: {o.get('unlocks')}",
                    "",
                    "Wallet gold lives on GameRuns characters as CURRENCY_ADVENTURE,",
                    "not in User.ftk2 LocalStats.",
                ]
            )
            unlocks = self._view.get("unlocks") or []
            if unlocks:
                lines.append("")
                lines.append("NewLoreStoreUnlocks:")
                lines.extend(f"  - {u}" for u in unlocks)
        else:
            house_rules = o.get("house_rules") if isinstance(o.get("house_rules"), dict) else None
            house_rules_label = "none"
            if house_rules:
                house_rules_label = str(len(house_rules))
            lines.extend(
                [
                    f"Save name: {o.get('title')}",
                    f"Run ID: {o.get('run_id')}",
                    f"Adventure: {o.get('adventure')}",
                    f"Difficulty: {o.get('difficulty')}",
                    f"Version: {o.get('version')}",
                    f"Date: {o.get('date')}",
                    f"Entities: {o.get('entity_count')}",
                    f"HouseRules: {house_rules_label}",
                    f"Run GOLD_COLLECTED: {o.get('gold_collected')}",
                    f"Run GOLD_SPENT: {o.get('gold_spent')}",
                    f"Party wallet total: {o.get('party_gold_total')}",
                ]
            )
            if house_rules:
                lines.append("")
                lines.append("HouseRules values:")
                for key, value in sorted(house_rules.items(), key=lambda item: str(item[0])):
                    lines.append(f"  - {key}: {value}")
        self.overview.setPlainText("\n".join(lines))

    def _populate_party(self) -> None:
        self.party_table.setSortingEnabled(False)
        self.party_table.setRowCount(0)
        self.party_table.setRowCount(len(self._party_rows))
        for row_idx, row in enumerate(self._party_rows):
            values = [
                row.get("name"),
                row.get("class"),
                row.get("health"),
                row.get("focus"),
                row.get("gold") if row.get("gold") is not None else "—",
                row.get("xp") if row.get("xp") is not None else "—",
                row.get("map_id") or "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row)
                self.party_table.setItem(row_idx, col, item)
        self.party_table.setSortingEnabled(True)

    def _populate_non_party(self) -> None:
        self.npc_table.setSortingEnabled(False)
        self.npc_table.setRowCount(0)
        self.npc_table.setRowCount(len(self._non_party_rows))
        for row_idx, row in enumerate(self._non_party_rows):
            values = [
                row.get("name"),
                row.get("class"),
                row.get("health"),
                row.get("focus"),
                row.get("gold") if row.get("gold") is not None else "—",
                row.get("xp") if row.get("xp") is not None else "—",
                row.get("map_id") or "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row)
                self.npc_table.setItem(row_idx, col, item)
        self.npc_table.setSortingEnabled(True)

    def _set_gold_controls_enabled(self, enabled: bool) -> None:
        self.gold_spin.setEnabled(enabled)
        self.apply_gold_btn.setEnabled(enabled)
        self.apply_all_gold_btn.setEnabled(enabled)
        for btn in self._gold_preset_buttons:
            btn.setEnabled(enabled)

    def _set_inventory_controls_enabled(self, enabled: bool) -> None:
        self.topup_herb_tool_btn.setEnabled(enabled)
        can_carry_over = self._view is not None and self._view.get("kind") == "run"
        self.carry_over_btn.setEnabled(can_carry_over)

    def _selected_party_row(self) -> dict[str, Any] | None:
        rows = self.party_table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if idx < 0:
            return None
        item = self.party_table.item(idx, 0)
        if item is None:
            return None
        row = item.data(Qt.ItemDataRole.UserRole)
        return row if isinstance(row, dict) else None

    def _on_party_select(self) -> None:
        row = self._selected_party_row()
        if row is None:
            self._set_gold_controls_enabled(False)
            self._set_inventory_controls_enabled(False)
            return
        self._populate_inventory(row)
        # Stay on Party tab so gold controls remain visible.
        can_edit = (
            self._view is not None
            and self._view.get("kind") == "run"
            and bool(row.get("guid"))
        )
        self._set_gold_controls_enabled(can_edit)
        self._set_inventory_controls_enabled(can_edit)
        if row.get("gold") is not None:
            self.gold_spin.setValue(int(row["gold"]))
        else:
            self.gold_spin.setValue(0)
        if can_edit:
            self.gold_hint.setText(f"Editing {row.get('name')} wallet (CURRENCY_ADVENTURE)")
        else:
            self.gold_hint.setText("Gold editing requires a GameRuns/*.ftk2 file.")

    def _on_party_double_click(self, row_idx: int, _col_idx: int) -> None:
        row = self._row_for_table(self.party_table, row_idx)
        if row is None:
            return
        self._open_inventory_window(row, title_prefix="Party Inventory")

    def _on_npc_double_click(self, row_idx: int, _col_idx: int) -> None:
        row = self._row_for_table(self.npc_table, row_idx)
        if row is None:
            return
        self._open_inventory_window(row, title_prefix="Non-Party Inventory")

    def apply_selected_gold(self) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to edit wallet gold.\n"
                "User.ftk2 only has lifetime GOLD_* stats, not party wallets.",
            )
            return
        row = self._selected_party_row()
        if row is None:
            QMessageBox.information(self, APP_TITLE, "Select a party member first.")
            return
        guid = row.get("guid")
        if not guid:
            QMessageBox.warning(self, APP_TITLE, "Selected character has no Guid.")
            return
        gold = int(self.gold_spin.value())
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Set {row.get('name')}'s gold to {gold:,}?\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            data = self._path.read_bytes()
            modified, ok = set_character_gold(data, str(guid), gold)
            if not ok:
                QMessageBox.critical(self, APP_TITLE, "Could not find that character in the run.")
                return
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Saved {row.get('name')} gold={gold:,} (backup {bak.name})"
            )
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def apply_gold_to_all_party(self) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to edit wallet gold.",
            )
            return
        targets = [row for row in self._party_rows if row.get("guid")]
        if not targets:
            QMessageBox.information(self, APP_TITLE, "No party characters with Guids found.")
            return
        gold = int(self.gold_spin.value())
        names = ", ".join(str(row.get("name")) for row in targets)
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Set gold to {gold:,} for all party members?\n\n{names}\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            data = self._path.read_bytes()
            for row in targets:
                data, ok = set_character_gold(data, str(row["guid"]), gold)
                if not ok:
                    QMessageBox.critical(
                        self,
                        APP_TITLE,
                        f"Could not update {row.get('name')}.",
                    )
                    return
            self._path.write_bytes(data)
            self.statusBar().showMessage(
                f"Saved gold={gold:,} for {len(targets)} characters (backup {bak.name})"
            )
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def _populate_inventory(self, row: dict[str, Any] | None) -> None:
        self.inventory_table.setSortingEnabled(False)
        self.inventory_table.setRowCount(0)
        if row is None:
            self.inventory_label.setText("Select a party member on the Party tab")
            self.inventory_table.setSortingEnabled(True)
            return
        gold = row.get("gold")
        self.inventory_label.setText(
            f"{row.get('name')} · {row.get('class')} · gold={gold if gold is not None else '—'}"
        )
        inventory = row.get("inventory") or []
        self.inventory_table.setRowCount(len(inventory))
        for i, entry in enumerate(inventory):
            self.inventory_table.setItem(i, 0, QTableWidgetItem(str(entry.get("type") or "")))
            self.inventory_table.setItem(i, 1, QTableWidgetItem(str(entry.get("config") or "")))
            self.inventory_table.setItem(i, 2, QTableWidgetItem(str(entry.get("count"))))
        self.inventory_table.setSortingEnabled(True)

    def apply_inventory_herb_tool_topup(self) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to edit party inventory.",
            )
            return
        row = self._selected_party_row()
        if row is None:
            QMessageBox.information(self, APP_TITLE, "Select a party member first.")
            return
        guid = row.get("guid")
        if not guid:
            QMessageBox.warning(self, APP_TITLE, "Selected character has no Guid.")
            return

        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Set all herb/tool/drink/scroll/safetystone stacks below 10 to 10 for {row.get('name')}?\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created if changes are needed."
            " Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            data = self._path.read_bytes()
            modified, ok, updated = ensure_character_herb_tool_minimum(
                data,
                str(guid),
                minimum=10,
            )
            if not ok:
                QMessageBox.critical(self, APP_TITLE, "Could not find that character in the run.")
                return
            if updated == 0:
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    f"No herb/tool/drink/scroll/safetystone stacks below 10 for {row.get('name')}.",
                )
                return

            bak = backup(self._path)
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Updated {updated} herb/tool/drink/scroll/safetystone stacks for {row.get('name')} (backup {bak.name})"
            )
            self._pending_select_guid = str(guid)
            self._pending_focus_inventory = True
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def apply_carry_over_consumables(self) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to carry consumables onto it.",
            )
            return
        source = find_carryover_source(self._path)
        if source is None:
            QMessageBox.information(
                self,
                APP_TITLE,
                "No other run save found on disk to carry consumables from.\n\n"
                "This feature copies herbs/drinks/tools/scrolls/safetystones from the most recent save of a different act.",
            )
            return

        source_name = run_display_name(source)
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Add the herbs/drinks/tools/scrolls/safetystones from\n{source_name} ({source.name})\n"
            f"onto the party of {run_display_name(self._path)}?\n\n"
            "Equipment, gold and XP are not copied.\n"
            "A .bak backup will be created if changes are needed.\n"
            "Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            target = self._path.read_bytes()
            source_data = source.read_bytes()
            modified, ok, updated = carry_over_consumables(target, source_data)
            if not ok:
                QMessageBox.critical(
                    self,
                    APP_TITLE,
                    "Could not read both saves as expedition runs with a party.",
                )
                return
            if updated == 0:
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    "No consumables found in the other act's save to carry over.",
                )
                return

            bak = backup(self._path)
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Carried over {updated} consumable entries from {source.name} (backup {bak.name})"
            )
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def _populate_stats(self) -> None:
        self.stats_table.setSortingEnabled(False)
        self.stats_table.setRowCount(0)
        if not self._view:
            self.stats_table.setSortingEnabled(True)
            return
        needle = self.stats_filter.text().strip().lower()
        rows = list(self._view.get("stats_rows") or [])
        if needle and isinstance(self._view.get("stats"), dict):
            rows = [
                (k, v)
                for k, v in sorted(self._view["stats"].items(), key=lambda item: str(item[0]))
                if needle in str(k).lower() or needle in str(v).lower()
            ]
        self.stats_table.setRowCount(len(rows))
        for i, (key, value) in enumerate(rows):
            self.stats_table.setItem(i, 0, QTableWidgetItem(str(key)))
            self.stats_table.setItem(i, 1, QTableWidgetItem(str(value)))
        self.stats_table.setSortingEnabled(True)

    def _populate_json_tree(self) -> None:
        self.json_tree.clear()
        if not self._view:
            return
        root = QTreeWidgetItem(["root", ""])
        self.json_tree.addTopLevelItem(root)
        self._insert_json_node(root, self._view.get("tree"), depth=0)
        root.setExpanded(True)

    def _insert_json_node(self, parent: QTreeWidgetItem, value: Any, *, depth: int) -> None:
        if depth > MAX_TREE_DEPTH:
            parent.addChild(QTreeWidgetItem(["…", ""]))
            return
        if isinstance(value, dict):
            parent.setText(1, f"{{{len(value)}}}")
            for i, (child_key, child_val) in enumerate(value.items()):
                if i >= MAX_TREE_CHILDREN:
                    parent.addChild(QTreeWidgetItem(["…", f"+{len(value) - i} more"]))
                    break
                child = QTreeWidgetItem([str(child_key), ""])
                parent.addChild(child)
                self._insert_json_node(child, child_val, depth=depth + 1)
        elif isinstance(value, list):
            parent.setText(1, f"[{len(value)}]")
            for i, child_val in enumerate(value):
                if i >= MAX_TREE_CHILDREN:
                    parent.addChild(QTreeWidgetItem(["…", f"+{len(value) - i} more"]))
                    break
                child = QTreeWidgetItem([f"[{i}]", ""])
                parent.addChild(child)
                self._insert_json_node(child, child_val, depth=depth + 1)
        else:
            preview = value
            if isinstance(preview, str) and len(preview) > 200:
                preview = preview[:197] + "…"
            parent.setText(1, "" if preview is None else str(preview))

    def export_json(self) -> None:
        if not self._path:
            QMessageBox.information(self, APP_TITLE, "Load a save first.")
            return
        out, _ = QFileDialog.getSaveFileName(
            self,
            "Export decrypted JSON",
            str(self._path.with_suffix(".json")),
            "JSON (*.json);;Text (*.txt);;All files (*)",
        )
        if not out:
            return
        try:
            plain = decrypt_ftk2_bytes(self._path.read_bytes())
            if plain.lstrip().startswith("//**"):
                Path(out).write_text(plain, encoding="utf-8")
            else:
                obj = json.loads(plain)
                Path(out).write_text(
                    json.dumps(obj, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            self.statusBar().showMessage(f"Exported {out}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Export failed:\n{exc}")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
