"""PySide6 GUI for browsing For The King II save files."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
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
    GODSBEARD_STACK_MINIMUM,
    HERB_STACK_MINIMUM,
    SCHOLARWORT_STACK_MINIMUM,
    KIBBLE_STACK_MINIMUM,
    add_character_thing,
    add_evil_reflection,
    add_mercenary,
    add_pet,
    backup,
    carry_over_consumables,
    decrypt_ftk2_bytes,
    ensure_character_herb_tool_minimum,
    ensure_party_herb_tool_minimum,
    ensure_party_food_minimum,
    grant_thing_to_party,
    remove_follower,
    repair_follower_placement,
    rename_party_member_synced,
    replace_character_thing,
    give_carnival_wheel_piece,
    set_carnival_tickets,
    set_character_gold,
    swap_character_class,
)
from ftk2_editor.viewmodel import (
    companion_catalog,
    companion_spec,
    consumable_catalog,
    find_carryover_source,
    healer_class_names,
    list_save_candidates,
    load_save_view,
    mercenary_catalog,
    mercenary_spec,
    playable_class_names,
    replacement_item_configs,
    run_display_name,
    unique_saved_items,
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


class ItemCatalogWorker(QThread):
    """Build the cross-save item catalog without blocking the GUI."""

    finished_ok = Signal(object)

    def run(self) -> None:
        self.finished_ok.emit(unique_saved_items())


class GameAssetsWorker(QThread):
    """Load the mercenary / playable-class catalogs without blocking the GUI."""

    finished_ok = Signal(object, object, object)

    def run(self) -> None:
        mercenaries = mercenary_catalog()
        playable = playable_class_names()
        companions = companion_catalog()
        self.finished_ok.emit(mercenaries, playable, companions)


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
        self._item_catalog: list[dict[str, str]] = []
        self._catalog_worker = ItemCatalogWorker(self)
        self._catalog_worker.finished_ok.connect(self._item_catalog.extend)
        self._mercenaries: list[dict[str, Any]] = []
        self._playable_classes: list[str] = []
        self._companions: list[dict[str, Any]] = []
        self._assets_worker = GameAssetsWorker(self)
        self._assets_worker.finished_ok.connect(self._on_game_assets_loaded)

        self._build_actions()
        self._build_ui()
        self.refresh_sidebar()
        self._catalog_worker.start()
        self._assets_worker.start()
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

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter = self.splitter
        layout.addWidget(splitter)

        left = QWidget()
        # Without a floor the pane collapses to its minimumSizeHint (112px),
        # which wraps the save paths one character per line.  The long path
        # hint above the list needs ~300px to stay readable.
        left.setMinimumWidth(280)
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

        self.party_table = QTableWidget(0, 8)
        self.party_table.setHorizontalHeaderLabels(
            ["Name", "Class", "HP", "Focus", "Gold", "XP", "Map", "Follower"]
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

        # One compact action bar: the two fields you edit inline (wallet gold and
        # display name) share a single Apply, and everything else that used to be
        # its own button lives behind Followers… / More actions.
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("Gold"))
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

        edit_row.addSpacing(16)
        edit_row.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Display name")
        self.name_edit.setMaxLength(64)
        self.name_edit.setEnabled(False)
        self.name_edit.setMinimumWidth(160)
        edit_row.addWidget(self.name_edit)

        self.apply_btn = QPushButton("Apply & save")
        self.apply_btn.setEnabled(False)
        self.apply_btn.setToolTip(
            "Write the gold and name shown above to the selected character "
            "(unchanged fields are skipped)"
        )
        self.apply_btn.clicked.connect(self.apply_selected)
        edit_row.addWidget(self.apply_btn)

        self.followers_btn = QPushButton("Followers…")
        self.followers_btn.setEnabled(False)
        self.followers_btn.setToolTip(
            "Recruit a mercenary or pet for the selected hero, or remove the "
            "follower they already have"
        )
        self.followers_btn.clicked.connect(self.open_followers_dialog)
        edit_row.addWidget(self.followers_btn)

        self.more_btn = QPushButton("More actions ▾")
        self.more_btn.setEnabled(False)
        self.more_btn.setToolTip("Party-wide top-ups, wheel piece, and class swap")
        self.more_menu = QMenu(self.more_btn)
        self.more_menu.setToolTipsVisible(True)
        self._build_more_menu()
        self.more_btn.setMenu(self.more_menu)
        edit_row.addWidget(self.more_btn)

        edit_row.addStretch(1)
        self.gold_hint = QLabel("Open a GameRuns/*.ftk2 save, select a character, edit gold or name, then Apply.")
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
        self.topup_herb_tool_btn = QPushButton("Top up selected character")
        self.topup_herb_tool_btn.setEnabled(False)
        self.topup_herb_tool_btn.setToolTip(
            "For selected character, set every herb/tool/drink/scroll/safetystone/thrown/orb/candy/MISC_INK stack below 10 up to 10"
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
        inv_action_row.addWidget(QLabel("Carnival tickets"))
        self.tickets_spin = QSpinBox()
        self.tickets_spin.setRange(0, 999_999)
        self.tickets_spin.setValue(50)
        self.tickets_spin.setEnabled(False)
        inv_action_row.addWidget(self.tickets_spin)
        self.tickets_btn = QPushButton("Set tickets")
        self.tickets_btn.setEnabled(False)
        self.tickets_btn.setToolTip(
            "Set the campaign Carnival Ticket pool (ItemPools.MISC_CARNIVALTICKET_01) "
            "so the Dark Carnival dungeon branches can be entered"
        )
        self.tickets_btn.clicked.connect(self.apply_carnival_tickets)
        inv_action_row.addWidget(self.tickets_btn)
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
        splitter.setSizes([320, 880])
        self._split_applied = False

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

    def _build_more_menu(self) -> None:
        """Populate the More actions menu (party-wide tools, not row fields)."""
        self._action_all_gold = QAction("Set gold for whole party", self)
        self._action_all_gold.setToolTip(
            "Set every real party member’s wallet to the gold shown in the "
            "Gold field (followers/mercs excluded)"
        )
        self._action_all_gold.triggered.connect(self.apply_gold_to_all_party)

        self._action_topup_party = QAction("Top up party consumables", self)
        self._action_topup_party.setToolTip(
            "Set every herb/tool/drink/scroll/safetystone/thrown/orb/candy/"
            "MISC_INK stack below 10 to 10 for all party members"
        )
        self._action_topup_party.triggered.connect(self.apply_party_herb_tool_topup)

        self._action_topup_snacks = QAction("Top up party snacks to 10", self)
        self._action_topup_snacks.setToolTip(
            "Set every snickerdoodle (SNICKERDOODLE_BASIC_01) and hotdog "
            "(HOTDOG_BASIC_01) stack below 10 to 10 for all party members"
        )
        self._action_topup_snacks.triggered.connect(self.apply_party_food_topup)

        self._action_wheel_piece = QAction("Give Carnival Wheel piece", self)
        self._action_wheel_piece.setToolTip(
            "Add one Carnival Wheel piece (MISC_WHEELPIECE_01, full-heal reward) "
            "to the selected character's inventory"
        )
        self._action_wheel_piece.triggered.connect(self.apply_give_wheel_piece)

        self._action_evil_reflection = QAction("Create evil reflection\u2026", self)
        self._action_evil_reflection.setToolTip(
            "Mirror the selected hero into a Dark Carnival Evil Reflection: a "
            "bound COMPANION (TypeArgs COMPANION_REFLECTION, Properties "
            "EVIL/REFLECTION) with the hero's own class, named 'Evil <hero>', "
            "placed beside them. Refuses if they already have a follower unless "
            "you tick Replace"
        )
        self._action_evil_reflection.triggered.connect(
            self.open_evil_reflection_dialog
        )

        self._action_give_consumable = QAction("Give consumable to party\u2026", self)
        self._action_give_consumable.setToolTip(
            "Pick any of the game's stackable consumables and give it to every "
            "party member (15 each by default), creating the stack for anyone "
            "who holds none"
        )
        self._action_give_consumable.triggered.connect(self.open_give_consumable_dialog)

        self._action_fix_followers = QAction("Fix invisible followers", self)
        self._action_fix_followers.setToolTip(
            "Give any bound follower that has no map position the hex and venue "
            "tile of the hero it follows, so the game actually draws it"
        )
        self._action_fix_followers.triggered.connect(self.apply_fix_followers)

        # Parent it in the constructor, like more_menu.  QMenu().setParent(w)
        # goes through the QWidget overload, which DROPS the Qt.Popup window
        # flag: the submenu then stops being a window and becomes an ordinary
        # child widget laid out at (0, 0) inside the window, painting the whole
        # playable-class list over the party table and the action bar (and
        # swallowing clicks on More actions).  QMenu(parent) keeps the flag.
        self._class_menu = QMenu(self.more_btn)
        self._class_menu.setTitle("Swap class")
        self._class_menu.setToolTipsVisible(True)
        self._rebuild_class_menu()

        self.more_menu.addAction(self._action_all_gold)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self._action_topup_party)
        self.more_menu.addAction(self._action_topup_snacks)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self._action_wheel_piece)
        self.more_menu.addAction(self._action_evil_reflection)
        self.more_menu.addAction(self._action_give_consumable)
        self.more_menu.addAction(self._action_fix_followers)
        self.more_menu.addMenu(self._class_menu)

    def _rebuild_class_menu(self) -> None:
        """(Re)fill the Swap class submenu from the loaded playable-class catalog."""
        self._class_menu.clear()
        if not self._playable_classes:
            empty = QAction("(no playable classes found)", self)
            empty.setEnabled(False)
            self._class_menu.addAction(empty)
            return
        for name in self._playable_classes:
            action = QAction(name, self)
            action.triggered.connect(
                lambda _checked=False, value=name: self.apply_swap_class(value)
            )
            self._class_menu.addAction(action)

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

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt naming)
        """Re-apply the sidebar split once the splitter has a real geometry.

        ``setSizes`` during __init__ is discarded: the splitter has no width
        yet, so the first real layout pass gives the Saves pane its
        minimumSizeHint instead.  Doing it on the first show sticks.
        """
        super().showEvent(event)
        if not self._split_applied:
            self._split_applied = True
            width = self.splitter.width()
            side = max(self.splitter.widget(0).minimumWidth(), 320)
            self.splitter.setSizes([side, max(200, width - side)])

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
            # A freshly loaded file has no selection; drop the action bar back to
            # its disabled state so More actions reflects the new save's kind.
            self._set_gold_controls_enabled(False)
            self.gold_hint.setText(
                "Select a character, edit gold or name, then Apply."
                if view.get("kind") == "run"
                else "Party editing needs a GameRuns/*.ftk2 expedition save."
            )
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
        # Capture GUID at dialog creation to avoid stale reference if main window selection changes
        character_guid = str(row.get("guid") or "")
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"{title_prefix}: {row.get('name')}")
        dialog.resize(760, 460)

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
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setRowCount(len(inventory))
        for i, entry in enumerate(inventory):
            item = QTableWidgetItem(str(entry.get("type") or ""))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            table.setItem(i, 0, item)
            table.setItem(i, 1, QTableWidgetItem(str(entry.get("config") or "")))
            table.setItem(i, 2, QTableWidgetItem(str(entry.get("count"))))
        table.setSortingEnabled(True)
        layout.addWidget(table)

        # Replace row: pick another item the party carries, optionally the same Type.
        replace_row = QHBoxLayout()
        replace_label = QLabel("Replace selected with:")
        replace_label.setStyleSheet("color: #9aa3ad;")
        replace_combo = QComboBox()
        replace_combo.setMinimumWidth(240)
        same_type_box = QCheckBox("Same type")
        same_type_box.setChecked(True)
        same_type_box.setToolTip(
            "When checked, match the item kind (BOW, BLUNT, HERB, etc.).\n"
            "Uncheck to list every distinct item found across all save games."
        )
        replace_btn = QPushButton("Replace item")
        replace_btn.setEnabled(False)
        replace_btn.setToolTip(
            "Swaps the selected item's ConfigName for the chosen one\n"
            "on this character only. Equipped-slot wiring and stack stay intact."
        )
        add_btn = QPushButton("Add item")
        add_btn.setEnabled(False)
        add_btn.setToolTip("Adds the chosen item to this character's inventory.")
        replace_row.addWidget(replace_label)
        replace_row.addWidget(replace_combo, 1)
        replace_row.addWidget(same_type_box)
        replace_row.addWidget(replace_btn)
        replace_row.addWidget(add_btn)
        layout.addLayout(replace_row)

        can_edit = (
            self._path is not None
            and self._view is not None
            and self._view.get("kind") == "run"
            and bool(character_guid)
        )

        def _replacement_catalog() -> list[dict[str, Any]]:
            return self._item_catalog or [
                item
                for party_row in self._party_rows
                for item in (party_row.get("inventory") or [])
            ]

        def _refresh_replace_options() -> None:
            replace_combo.clear()
            replace_btn.setEnabled(False)
            add_btn.setEnabled(False)
            if not can_edit:
                return
            selected = table.selectionModel().selectedRows()
            if not selected:
                options = replacement_item_configs(
                    _replacement_catalog(), {}, same_type=False
                )
                if not options:
                    replace_label.setText("Add from saved catalog: (no items found in saves)")
                    return
                replace_label.setText("Add from saved catalog:")
                replace_combo.addItems(options)
                add_btn.setEnabled(True)
                return
            cell = table.item(selected[0].row(), 0)
            if cell is None:
                return
            entry = cell.data(Qt.ItemDataRole.UserRole)
            if not isinstance(entry, dict):
                return
            options = replacement_item_configs(
                _replacement_catalog(), entry, same_type=same_type_box.isChecked()
            )
            if not options:
                replace_label.setText(
                    "Replace selected with: (no matching items found in saves)"
                )
                return
            replace_label.setText("Replace selected with:")
            replace_combo.addItems(options)
            replace_btn.setEnabled(True)
            add_btn.setEnabled(True)

        table.itemSelectionChanged.connect(_refresh_replace_options)
        same_type_box.toggled.connect(_refresh_replace_options)
        _refresh_replace_options()

        def _apply_replace() -> None:
            if not self._path or self._view is None or self._view.get("kind") != "run":
                QMessageBox.warning(
                    self, APP_TITLE, "Open a GameRuns/*.ftk2 expedition save to replace items."
                )
                return
            selected = table.selectionModel().selectedRows()
            if not selected:
                QMessageBox.information(self, APP_TITLE, "Select an item row first.")
                return
            cell = table.item(selected[0].row(), 0)
            if cell is None:
                return
            entry = cell.data(Qt.ItemDataRole.UserRole)
            if not isinstance(entry, dict):
                return
            thing_id = entry.get("id")
            new_config = replace_combo.currentText()
            guid = character_guid
            if not guid:
                QMessageBox.warning(self, APP_TITLE, "That inventory row has no character ID.")
                return
            if not thing_id or not new_config:
                return
            old_config = entry.get("config")
            reply = QMessageBox.question(
                self,
                APP_TITLE,
                f"Replace {old_config} with {new_config} on {row.get('name')}?\n\n"
                f"File: {self._path}\n"
                "A .bak backup will be created. Quit the game first if it is running.",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                bak = backup(self._path)
                data = self._path.read_bytes()
                modified, ok = replace_character_thing(
                    data, str(guid), thing_id, new_config
                )
                if not ok:
                    QMessageBox.critical(self, APP_TITLE, "Could not find that item in the run.")
                    return
                self._path.write_bytes(modified)
                self.statusBar().showMessage(
                    f"Replaced {old_config} → {new_config} on {row.get('name')} (backup {bak.name})"
                )
                dialog.close()
                self.load_path(self._path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

        replace_btn.clicked.connect(_apply_replace)

        def _apply_add() -> None:
            if not self._path or self._view is None or self._view.get("kind") != "run":
                QMessageBox.warning(
                    self, APP_TITLE, "Open a GameRuns/*.ftk2 expedition save to add items."
                )
                return
            config = replace_combo.currentText()
            guid = character_guid
            if not guid:
                QMessageBox.warning(self, APP_TITLE, "That inventory row has no character ID.")
                return
            catalog_item = next(
                (item for item in _replacement_catalog() if item.get("config") == config), None
            )
            if not config or catalog_item is None:
                return
            reply = QMessageBox.question(
                self,
                APP_TITLE,
                f"Add {config} to {row.get('name')}'s inventory?\n\n"
                f"File: {self._path}\n"
                "A .bak backup will be created. Quit the game first if it is running.",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                bak = backup(self._path)
                modified, ok = add_character_thing(
                    self._path.read_bytes(),
                    str(guid),
                    config,
                    str(catalog_item.get("type") or "ITEM"),
                    str(catalog_item.get("expansion") or "BASE"),
                )
                if not ok:
                    QMessageBox.critical(self, APP_TITLE, "Could not find that character in the run.")
                    return
                self._path.write_bytes(modified)
                self.statusBar().showMessage(
                    f"Added {config} to {row.get('name')} (backup {bak.name})"
                )
                dialog.close()
                self.load_path(self._path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

        add_btn.clicked.connect(_apply_add)

        self._inventory_windows.append(dialog)
        dialog.finished.connect(lambda _code: self._inventory_windows.remove(dialog) if dialog in self._inventory_windows else None)
        dialog.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._load_generation += 1  # ignore late UI updates
        self._stop_loader()
        self._catalog_worker.wait()
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
            if row.get("follower_name"):
                follower_col = f"has {row['follower_name']}"
            elif row.get("follows_name"):
                follower_col = f"pet of {row['follows_name']}"
            else:
                follower_col = ""
            values = [
                row.get("name"),
                row.get("class"),
                row.get("health"),
                row.get("focus"),
                row.get("gold") if row.get("gold") is not None else "—",
                row.get("xp") if row.get("xp") is not None else "—",
                row.get("map_id") or "",
                follower_col,
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
        """Enable the inline fields for the selected row and refresh More actions."""
        self.gold_spin.setEnabled(enabled)
        self.apply_btn.setEnabled(enabled)
        for btn in self._gold_preset_buttons:
            btn.setEnabled(enabled)
        self.name_edit.setEnabled(enabled)
        run_ok = self._view is not None and self._view.get("kind") == "run"
        self.more_btn.setEnabled(run_ok)
        # The Followers dialog is only meaningful for a selected character, and it
        # decides for itself whether that character is a host or a follower.
        self.followers_btn.setEnabled(enabled and run_ok)
        self._sync_more_menu_state()

    def _sync_more_menu_state(self) -> None:
        """Enable exactly the More actions entries the current save allows.

        Every entry's state is assigned here, in both directions.  A
        disable-only version left the party-wide entries (top-ups, Fix
        invisible followers) stuck off once a non-run save had been opened --
        they were only ever cleared, never restored, so a later GameRuns save
        still showed a dead menu.
        """
        row = self._selected_party_row()
        has_row = row is not None and bool(row.get("guid"))
        run_ok = self._view is not None and self._view.get("kind") == "run"
        needs_row = run_ok and has_row
        # The button opens the menu, so it only needs a run save -- the
        # selection-independent entries inside must stay reachable.
        self.more_btn.setEnabled(run_ok)
        self._action_all_gold.setEnabled(needs_row)
        self._action_wheel_piece.setEnabled(needs_row)
        # Party-wide: no selection needed, but an expedition save does.
        self._action_topup_party.setEnabled(run_ok)
        self._action_topup_snacks.setEnabled(run_ok)
        self._action_give_consumable.setEnabled(run_ok)
        self._action_evil_reflection.setEnabled(needs_row)
        self._action_fix_followers.setEnabled(run_ok)
        self._class_menu.setEnabled(needs_row and bool(self._playable_classes))
        if not self._playable_classes:
            self._class_menu.setToolTip(
                "Playable-class catalog unavailable (game assets not found). "
                "Launch the game once, then reopen the editor."
            )
        else:
            self._class_menu.setToolTip(
                "Change the selected character's class (CharacterComponent.ConfigName)"
            )

    def _set_inventory_controls_enabled(self, enabled: bool) -> None:
        self.topup_herb_tool_btn.setEnabled(enabled)
        can_run = self._view is not None and self._view.get("kind") == "run"
        self.carry_over_btn.setEnabled(can_run)
        self.tickets_btn.setEnabled(can_run)
        self.tickets_spin.setEnabled(can_run)

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
            if row.get("follower_name"):
                self.gold_hint.setText(
                    f"Editing {row.get('name')} — has follower "
                    f"{row['follower_name']} (Followers… manages it)"
                )
            elif row.get("follows_name"):
                self.gold_hint.setText(
                    f"Editing {row.get('name')} — follower of {row['follows_name']}"
                )
            else:
                self.gold_hint.setText(
                    f"Editing {row.get('name')} · gold is CURRENCY_ADVENTURE"
                )
            self.name_edit.setText(str(row.get("name") or ""))
        else:
            self.gold_hint.setText("Editing requires a GameRuns/*.ftk2 file.")
            self.name_edit.clear()

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

    def apply_selected(self) -> None:
        """Write the Gold and Name fields of the action bar to the selected row.

        Both edits are staged in memory first, so one confirm covers both and a
        failure on either leaves the save untouched.  A rename can also touch the
        campaign roster in User.ftk2; that file is only written after the run has
        been prepared, and is rolled back from its backup if the run write fails.
        """
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to edit party members.\n"
                "User.ftk2 only has lifetime GOLD_* stats, not run wallets or rosters.",
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

        old_name = str(row.get("name") or "")
        new_name = self.name_edit.text().strip()
        new_gold = int(self.gold_spin.value())
        old_gold = row.get("gold")
        wants_rename = bool(new_name) and new_name != old_name
        wants_gold = old_gold is None or int(old_gold) != new_gold
        if not wants_rename and not wants_gold:
            QMessageBox.information(
                self,
                APP_TITLE,
                "Nothing to apply — the Gold and Name fields match the save.",
            )
            return
        if not new_name:
            new_name = old_name

        changes = []
        if wants_rename:
            changes.append(f"Rename {old_name!r} -> {new_name!r}.")
        if wants_gold:
            changes.append(f"Set gold to {new_gold:,}.")
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"{old_name or 'This character'}:\n" + "\n".join(changes) + "\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            original = self._path.read_bytes()
            data = original
            user_path: Path | None = None
            user_modified: bytes | None = None
            if wants_rename:
                user_path = self._locate_user_save()
                user_data = user_path.read_bytes() if user_path else None
                data, ok, user_modified = rename_party_member_synced(
                    data, new_name, guid=str(guid), user_data=user_data
                )
                if not ok:
                    QMessageBox.critical(
                        self, APP_TITLE, "Could not find that character in the run."
                    )
                    return
            if wants_gold:
                data, ok = set_character_gold(data, str(guid), new_gold)
                if not ok:
                    QMessageBox.critical(
                        self, APP_TITLE, "Could not find that character in the run."
                    )
                    return
            # Both edits are staged; back up the roster, then commit User + run
            # together so a half-finished write cannot leave them disagreeing.
            user_bak: Path | None = None
            user_original: bytes | None = None
            if user_path is not None and user_modified is not None:
                user_bak = backup(user_path)
                user_original = user_path.read_bytes()
            try:
                if user_bak is not None and user_path is not None and user_modified is not None:
                    user_path.write_bytes(user_modified)
                self._path.write_bytes(data)
            except Exception:
                if user_original is not None and user_path is not None:
                    user_path.write_bytes(user_original)
                self._path.write_bytes(original)
                raise
            message = f"{old_name}: " + ", ".join(changes) + f" (backup {bak.name})"
            if user_bak is not None and user_path is not None:
                message += f" + {user_path.name} roster (backup {user_bak.name})"
            self.statusBar().showMessage(message)
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def _locate_user_save(self) -> Path | None:
        """The User.ftk2 two folders above the run (sibling of GameRuns/), if present."""
        if not self._path:
            return None
        candidate = self._path.parent.parent / "User.ftk2"
        if candidate.exists() and candidate != self._path:
            return candidate
        return None

    def apply_gold_to_all_party(self) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to edit wallet gold.",
            )
            return
        targets = [
            row for row in self._party_rows
            if row.get("guid") and row.get("has_player_component")
        ]
        if not targets:
            QMessageBox.information(self, APP_TITLE, "No player-controlled party members with Guids found.")
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
            f"Top up consumables for {row.get('name')}?\n\n"
            "Herbs go to 15 (Scholar's Wort to 10); kibble to 50 if they own a pet; "
            "godsbeard to 50 if they heal. "
            "Other herb/tool/drink/scroll/safetystone/thrown/orb/candy/MISC_INK stacks below 10 go to 10.\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created if changes are needed."
            " Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            guid = str(guid)
            healers = {guid} if str(row.get("class") or "") in healer_class_names() else set()
            data = self._path.read_bytes()
            modified, ok, updated = ensure_character_herb_tool_minimum(
                data,
                guid,
                minimum=10,
                herb_minimum=HERB_STACK_MINIMUM,
                kibble_minimum=KIBBLE_STACK_MINIMUM,
                godsbeard_minimum=GODSBEARD_STACK_MINIMUM,
                scholarwort_minimum=SCHOLARWORT_STACK_MINIMUM,
                pet_owners=self._view.get("pet_owners") or set(),
                healers=healers,
            )
            if not ok:
                QMessageBox.critical(self, APP_TITLE, "Could not find that character in the run.")
                return
            if updated == 0:
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    f"{row.get('name')} is already topped up.\n\n"
                    "Herb stacks are at least 15 (Scholar's Wort at least 10), kibble at least 50 "
                    "for pet owners, godsbeard at least 50 for healers, and every other consumable "
                    "stack is at least 10.\n\n"
                    "No changes were made and no backup was created.",
                )
                return

            bak = backup(self._path)
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Updated {updated} consumable stacks for {row.get('name')} (backup {bak.name})"
            )
            self._pending_select_guid = str(guid)
            self._pending_focus_inventory = True
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def apply_party_herb_tool_topup(self) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to edit party inventory.",
            )
            return
        targets = [
            row for row in self._party_rows
            if row.get("guid") and row.get("has_player_component")
        ]
        if not targets:
            QMessageBox.information(self, APP_TITLE, "No player-controlled party members with Guids found.")
            return
        names = ", ".join(str(row.get("name")) for row in targets)
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            "Top up consumables for all party members?\n\n"
            "Herbs go to 15 (Scholar's Wort to 10); kibble to 50 for pet owners; "
            "godsbeard to 50 for healers. "
            "Other herb/tool/drink/scroll/safetystone/thrown/orb/candy/MISC_INK stacks below 10 go to 10.\n\n"
            f"{names}\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created if changes are needed."
            " Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            guids = [str(row["guid"]) for row in targets]
            healer_classes = healer_class_names()
            healers = {
                str(row["guid"])
                for row in targets
                if str(row.get("class") or "") in healer_classes
            }
            data = self._path.read_bytes()
            modified, ok, updated = ensure_party_herb_tool_minimum(
                data,
                guids,
                minimum=10,
                herb_minimum=HERB_STACK_MINIMUM,
                kibble_minimum=KIBBLE_STACK_MINIMUM,
                godsbeard_minimum=GODSBEARD_STACK_MINIMUM,
                scholarwort_minimum=SCHOLARWORT_STACK_MINIMUM,
                pet_owners=self._view.get("pet_owners") or set(),
                healers=healers,
            )
            if not ok:
                QMessageBox.critical(self, APP_TITLE, "Could not find any party members in the run.")
                return
            if updated == 0:
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    "The party is already topped up.\n\n"
                    "Herb stacks are at least 15 (Scholar's Wort at least 10), kibble at least 50 "
                    "for pet owners, godsbeard at least 50 for healers, and every other consumable "
                    "stack is at least 10.\n\n"
                    "No changes were made and no backup was created.",
                )
                return
            bak = backup(self._path)
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Updated {updated} consumable stacks across {len(targets)} characters (backup {bak.name})"
            )
            self._pending_select_guid = str(targets[0]["guid"])
            self._pending_focus_inventory = True
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def apply_party_food_topup(self) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to top up party snacks.",
            )
            return
        targets = [
            row for row in self._party_rows
            if row.get("guid") and row.get("has_player_component")
        ]
        if not targets:
            QMessageBox.information(self, APP_TITLE, "No player-controlled party members with Guids found.")
            return
        names = ", ".join(str(row.get("name")) for row in targets)
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            "Set every snickerdoodle (SNICKERDOODLE_BASIC_01) and hotdog (HOTDOG_BASIC_01) "
            "stack below 10 to 10 for all party members?\n\n"
            f"{names}\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created if changes are needed."
            " Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            guids = [str(row["guid"]) for row in targets]
            data = self._path.read_bytes()
            modified, ok, updated = ensure_party_food_minimum(data, guids, minimum=10)
            if not ok:
                QMessageBox.critical(self, APP_TITLE, "Could not find any party members in the run.")
                return
            if updated == 0:
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    "The party's snacks are already topped up.\n\n"
                    "Every existing snickerdoodle and hotdog stack is at least 10.\n\n"
                    "No changes were made and no backup was created.",
                )
                return
            bak = backup(self._path)
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Updated {updated} snack stacks (snickerdoodle/hotdog to 10) across {len(targets)} characters (backup {bak.name})"
            )
            self._pending_select_guid = str(targets[0]["guid"])
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

    def apply_carnival_tickets(self) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to set Carnival tickets.",
            )
            return
        amount = self.tickets_spin.value()
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            "Set the campaign Carnival Ticket pool\n"
            f"(ItemPools.MISC_CARNIVALTICKET_01) to {amount}?\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created.\n"
            "Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            data = self._path.read_bytes()
            modified, ok = set_carnival_tickets(data, amount)
            if not ok:
                QMessageBox.critical(
                    self,
                    APP_TITLE,
                    "Could not set Carnival tickets (not a GameRun or has no ItemPools).",
                )
                return
            self._path.write_bytes(modified)
            self.statusBar().showMessage(f"Set Carnival tickets = {amount} (backup {bak.name})")
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def apply_give_wheel_piece(self) -> None:
        """Set a hero's Wheel Wedge count (MISC_WHEELPIECE_01).

        Opens a count dialog rather than writing straight away: the helper
        refuses a second wedge when the hero already holds one, so a plain
        "give one" button reported a misleading failure for anyone who had
        already been given wedges.  The stack is *set* to the chosen count.
        """
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to give a wheel piece.",
            )
            return
        row = self._selected_party_row()
        if row is None:
            QMessageBox.information(self, APP_TITLE, "Select a party member first.")
            return
        guid = row.get("guid")
        name = str(row.get("name") or "?")
        if not guid:
            QMessageBox.warning(self, APP_TITLE, "Selected character has no Guid.")
            return

        held = 0
        for item in row.get("inventory") or []:
            if isinstance(item, dict) and item.get("config") == "MISC_WHEELPIECE_01":
                try:
                    held = int(item.get("count") or 0)
                except (TypeError, ValueError):
                    held = 0

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"Wheel Wedge \u2014 {name}")
        dialog.resize(460, 200)
        layout = QVBoxLayout(dialog)
        body = QLabel(
            f"Wheel Wedge (MISC_WHEELPIECE_01) for {name}.\n\n"
            + (
                f"Currently holding {held}. The stack is set to the number you "
                "choose."
                if held
                else "They hold none. The stack is created with the number you "
                "choose."
            )
        )
        body.setWordWrap(True)
        layout.addWidget(body)
        row_layout = QHBoxLayout()
        row_layout.addWidget(QLabel("Wedges"))
        spin = QSpinBox()
        spin.setRange(1, 999)
        spin.setValue(held + 1 if held else 1)
        spin.setFixedWidth(90)
        row_layout.addWidget(spin)
        row_layout.addStretch(1)
        layout.addLayout(row_layout)

        def _apply() -> None:
            count = int(spin.value())
            reply = QMessageBox.question(
                self,
                APP_TITLE,
                f"Set {name}'s Wheel Wedges to {count}?\n\n"
                + (
                    f"They hold {held} now, so this is a top-up."
                    if held and count > held
                    else f"They hold {held} now, so this reduces the stack."
                    if held
                    else "This creates the stack."
                )
                + f"\n\nFile: {self._path}\n"
                "A .bak backup will be created. Quit the game first if it is running.",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                bak = backup(self._path)
                data = self._path.read_bytes()
                modified, ok = give_carnival_wheel_piece(
                    data, str(guid), count=count, replace=True
                )
                if not ok:
                    QMessageBox.warning(
                        self,
                        APP_TITLE,
                        f"Could not write the wheel wedges for {name} "
                        "(not a GameRun, or no such character).",
                    )
                    return
                self._path.write_bytes(modified)
                self.statusBar().showMessage(
                    f"Set {name}'s Wheel Wedges to {count} (backup {bak.name})"
                )
                self._pending_select_guid = str(guid)
                dialog.close()
                self.load_path(self._path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

        ok_btn = QPushButton("Set wheel wedges & save")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(_apply)
        layout.addWidget(ok_btn)
        layout.addStretch(1)
        dialog.show()
        self._inventory_windows.append(dialog)

    def apply_fix_followers(self) -> None:
        """More actions -> Fix invisible followers: back-fill map placement."""
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to fix followers.",
            )
            return
        try:
            data = self._path.read_bytes()
            modified, ok, repaired = repair_follower_placement(data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Could not read the save:\n{exc}")
            return
        if not ok:
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Could not inspect followers (not a GameRun or invalid structure).",
            )
            return
        if not repaired:
            QMessageBox.information(
                self,
                APP_TITLE,
                "Every bound follower already has a map position — nothing to fix.",
            )
            return
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Give {len(repaired)} follower(s) a map position?\n\n"
            "They are bound in PlayerFollowers and alive, but were saved with no "
            "hex or venue tile, which is why the game never draws them. This "
            "copies the position of the hero each one follows and puts it on a "
            "free tile beside that hero.\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Placed {len(repaired)} follower(s) (backup {bak.name})"
            )
            self._pending_select_guid = None
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def _on_game_assets_loaded(
        self, mercenaries: object, classes: object, companions: object
    ) -> None:
        self._mercenaries = list(mercenaries) if isinstance(mercenaries, list) else []
        self._playable_classes = (
            [str(c) for c in classes] if isinstance(classes, list) else []
        )
        self._companions = list(companions) if isinstance(companions, list) else []
        self._rebuild_class_menu()
        if not (self._mercenaries or self._companions):
            self.followers_btn.setToolTip(
                "Follower catalog unavailable (game assets under For The King II "
                "not found). Install/launch the game once, then reopen the editor."
            )
        else:
            self.followers_btn.setToolTip(
                "Recruit a mercenary or pet for the selected hero, or remove the "
                "follower they already have"
            )
        self._sync_more_menu_state()

    # ------------------------------------------------------------------
    # Followers: one dialog for recruiting a mercenary or a pet and for
    # removing whichever follower a character has.  Both were separate
    # combo/tier/button triples before; they share the same entity shape and
    # the same PlayerFollowers binding, so they share one flow here.
    # ------------------------------------------------------------------

    @staticmethod
    def _tier_range(entry: object) -> tuple[int, int]:
        """Tier bounds for a catalog entry, defaulting to the game's 0-7 range."""
        tiers = entry.get("tiers") if isinstance(entry, dict) else None
        if not isinstance(tiers, list) or not tiers:
            return (0, 7)
        return (int(min(tiers)), int(max(tiers)))

    def _recruit_options(self) -> list[dict[str, Any]]:
        """Every recruitable follower as one list: kind, class name, tiers."""
        options: list[dict[str, Any]] = []
        for kind, catalog in (("mercenary", self._mercenaries), ("pet", self._companions)):
            for entry in catalog:
                if not isinstance(entry, dict):
                    continue
                class_name = str(entry.get("class_name") or entry.get("config_base") or "")
                if not class_name:
                    continue
                low, high = self._tier_range(entry)
                options.append(
                    {
                        "kind": kind,
                        "class_name": class_name,
                        "tiers": list(range(low, high + 1)),
                    }
                )
        options.sort(key=lambda item: (item["kind"], item["class_name"]))
        return options

    def open_evil_reflection_dialog(self) -> None:
        """More actions -> Create evil reflection: mirror the selected hero."""
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to create a reflection.",
            )
            return
        row = self._selected_party_row()
        if row is None or not row.get("guid"):
            QMessageBox.information(self, APP_TITLE, "Select a hero first.")
            return
        if not row.get("has_player_component"):
            QMessageBox.information(
                self,
                APP_TITLE,
                f"{row.get('name')} is not a player-controlled hero, so it has no "
                "reflection to mirror. Select a hero row instead.",
            )
            return

        held = row.get("follower_guid")
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"Evil Reflection \u2014 {row.get('name')}")
        dialog.resize(560, 240)
        layout = QVBoxLayout(dialog)
        body = QLabel(
            f"Creates a Dark Carnival Evil Reflection of {row.get('name')}: a bound "
            "companion with the same class, named \u201cEvil "
            f"{row.get('name')}\u201d, standing beside them.\n\n"
            "It is tagged Properties EVIL/REFLECTION, which is how the game "
            "itself marks the ones it spawns in the Carnival."
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        inventory_box = QCheckBox("Mirror the hero's gear and consumables")
        inventory_box.setChecked(True)
        inventory_box.setToolTip(
            "A real reflection carries a full class loadout. Off means it gets "
            "only its own (empty) gold and XP counters"
        )
        layout.addWidget(inventory_box)

        replace_box = QCheckBox(
            f"Replace the current follower ({row.get('follower_name') or held})"
            if held
            else "Replace the current follower"
        )
        replace_box.setChecked(False)
        replace_box.setEnabled(bool(held))
        if held:
            replace_box.setToolTip(
                "A hero holds one follower (PlayerFollowers is a map). Ticking "
                "this deletes the current follower's binding and overwrites the "
                "slot; the old entity stays in the save, unbound."
            )
        else:
            replace_box.setToolTip("This hero has a free follower slot.")
        layout.addWidget(replace_box)

        create_btn = QPushButton("Create reflection & save")
        create_btn.setDefault(True)
        create_btn.clicked.connect(
            lambda: self._create_evil_reflection(
                str(row["guid"]),
                str(row.get("name") or "?"),
                bool(inventory_box.isChecked()),
                bool(replace_box.isChecked()),
                str(row.get("follower_name") or held or ""),
                dialog,
            )
        )
        layout.addWidget(create_btn)
        layout.addStretch(1)
        dialog.show()
        self._inventory_windows.append(dialog)

    def _create_evil_reflection(
        self,
        host_guid: str,
        host_name: str,
        copy_inventory: bool,
        replace: bool,
        held_name: str,
        dialog: QDialog,
    ) -> None:
        """Confirm, write the reflection for *host_guid*, then reload."""
        if not self._path:
            return
        extra = (
            f"\n\nThis replaces {held_name}, who stops being bound to "
            f"{host_name} (their entity stays in the save, unbound)."
            if replace and held_name
            else ""
        )
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Create an Evil Reflection of {host_name}?{extra}\n\n"
            + (
                "It mirrors the hero's gear and consumables; its own gold and XP "
                "start at zero.\n\n"
                if copy_inventory
                else "It gets no gear \u2014 only its own empty counters.\n\n"
            )
            + f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            data = self._path.read_bytes()
            modified, ok, _guid = add_evil_reflection(
                data, host_guid, replace=replace, copy_inventory=copy_inventory
            )
            if not ok:
                QMessageBox.critical(
                    self,
                    APP_TITLE,
                    "Could not create the reflection (not a GameRun, unknown hero, "
                    "or they already have a follower \u2014 tick Replace to "
                    "overwrite the slot).",
                )
                return
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Created Evil Reflection of {host_name} (backup {bak.name})"
            )
            self._pending_select_guid = host_guid
            dialog.close()
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def open_give_consumable_dialog(self) -> None:
        """More actions -> Give consumable to party: pick any consumable, grant it."""
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to give a consumable.",
            )
            return
        targets = [
            row
            for row in self._party_rows
            if row.get("guid") and row.get("has_player_component")
        ]
        if not targets:
            QMessageBox.information(
                self, APP_TITLE, "No player-controlled party members with Guids found."
            )
            return

        catalog = consumable_catalog()
        if not catalog:
            QMessageBox.warning(
                self,
                APP_TITLE,
                "No consumable catalog available. The game's Things/ configs were "
                "not found under the FTK2 install — launch the game once, then "
                "reopen the editor.",
            )
            return

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle("Give consumable to party")
        dialog.resize(620, 220)
        layout = QVBoxLayout(dialog)
        subtitle = QLabel(
            f"Every party member gets the stack. Currently: "
            f"{len(catalog)} consumables in the game's Things/ configs."
        )
        subtitle.setStyleSheet("color: #9aa3ad;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        filter_edit = QLineEdit()
        filter_edit.setPlaceholderText("Filter by name, class or config\u2026")
        filter_edit.setClearButtonEnabled(True)
        layout.addWidget(filter_edit)

        row = QHBoxLayout()
        combo = QComboBox()
        combo.setMinimumWidth(380)
        row.addWidget(combo, 1)
        count_label = QLabel("Each")
        count_label.setStyleSheet("color: #9aa3ad;")
        row.addWidget(count_label)
        count_spin = QSpinBox()
        count_spin.setRange(1, 9999)
        count_spin.setValue(15)
        count_spin.setFixedWidth(90)
        count_spin.setToolTip("Stack count per party member")
        row.addWidget(count_spin)
        layout.addLayout(row)

        shown: list[dict[str, Any]] = []

        def _rebuild() -> None:
            needle = filter_edit.text().strip().lower()
            combo.clear()
            shown.clear()
            for entry in catalog:
                haystack = " ".join(
                    (
                        str(entry.get("name") or ""),
                        str(entry.get("class") or ""),
                        str(entry.get("config") or ""),
                        str(entry.get("rarity") or ""),
                    )
                ).lower()
                if needle and needle not in haystack:
                    continue
                shown.append(entry)
                combo.addItem(
                    f"{entry['name']}  ·  {entry['class']}  ·  {entry['config']}", entry
                )
            if not shown:
                combo.addItem("(no consumable matches that filter)", None)
                combo.setEnabled(False)
            else:
                combo.setEnabled(True)

        def _on_filter(_text: str) -> None:
            _rebuild()

        def _on_give() -> None:
            entry = combo.currentData()
            if not isinstance(entry, dict) or not entry.get("config"):
                QMessageBox.information(self, APP_TITLE, "Select a consumable first.")
                return
            self._give_consumable_to_party(
                str(entry["config"]),
                str(entry.get("name") or entry["config"]),
                count_spin.value(),
                dialog,
            )

        filter_edit.textChanged.connect(_on_filter)
        _rebuild()
        give_btn = QPushButton("Give to whole party & save")
        give_btn.setDefault(True)
        give_btn.clicked.connect(_on_give)
        layout.addWidget(give_btn)
        layout.addStretch(1)
        dialog.show()
        self._inventory_windows.append(dialog)

    def _give_consumable_to_party(
        self,
        config: str,
        label: str,
        count: int,
        dialog: QDialog,
    ) -> None:
        """Confirm, write *count* of *config* to every party member, reload."""
        if not self._path:
            return
        targets = [
            row
            for row in self._party_rows
            if row.get("guid") and row.get("has_player_component")
        ]
        guids = [str(row["guid"]) for row in targets]
        names = ", ".join(str(row.get("name")) for row in targets)
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Give {count} \u00d7 {label} ({config}) to every party member?\n\n"
            "Anyone already holding the item has their stack raised to this count; "
            "anyone holding none is given a fresh stack.\n\n"
            f"{names}\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            data = self._path.read_bytes()
            modified, ok, changed = grant_thing_to_party(data, guids, config, count)
            if not ok:
                QMessageBox.critical(
                    self,
                    APP_TITLE,
                    "Could not give the consumable (not a GameRun or invalid structure).",
                )
                return
            if changed == 0:
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    f"Everyone already holds at least {count} \u00d7 {label}. "
                    "No changes were made and no backup was created.",
                )
                return
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Gave {count} \u00d7 {label} to {changed} party member(s) "
                f"(backup {bak.name})"
            )
            self._pending_select_guid = None
            dialog.close()
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def open_followers_dialog(self) -> None:
        """Manage the follower of the selected character (recruit or remove)."""
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to manage followers.",
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

        is_host = bool(row.get("has_player_component"))
        ctype = str(row.get("character_type") or "")
        is_follower = (not is_host) and ctype in ("MERCENARY", "COMPANION")

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"Followers — {row.get('name')}")
        dialog.resize(560, 260)
        layout = QVBoxLayout(dialog)
        subtitle = QLabel(f"{row.get('name')} · {row.get('class')} · {ctype or 'STANDARD'}")
        subtitle.setStyleSheet("color: #9aa3ad;")
        layout.addWidget(subtitle)

        if is_follower:
            label = "pet" if ctype == "COMPANION" else "mercenary"
            owner = row.get("follows_name") or row.get("follows_guid") or "an unknown hero"
            body = QLabel(
                f"{row.get('name')} is the {label} of {owner}.\n"
                "Remove it to free that hero's follower slot."
            )
            body.setWordWrap(True)
            layout.addWidget(body)
            remove_btn = QPushButton(f"Remove this {label} & save")
            remove_btn.setToolTip(
                "Delete the follower's entity and its PlayerFollowers binding"
            )
            remove_btn.clicked.connect(
                lambda: self._remove_follower(
                    str(guid), str(row.get("name") or "?"), label, str(owner), dialog
                )
            )
            layout.addWidget(remove_btn)
            layout.addStretch(1)
            dialog.show()
            self._inventory_windows.append(dialog)
            return

        if not is_host:
            body = QLabel(
                f"{row.get('name')} is not a player-controlled hero, so it cannot "
                "recruit a follower. Select a hero row instead."
            )
            body.setWordWrap(True)
            layout.addWidget(body)
            layout.addStretch(1)
            dialog.show()
            self._inventory_windows.append(dialog)
            return

        current_guid = row.get("follower_guid")
        current = QLabel()
        current.setWordWrap(True)
        if current_guid:
            current.setText(
                f"Currently following {row.get('name')}: "
                f"{row.get('follower_name') or current_guid}."
            )
            remove_btn = QPushButton("Remove follower & save")
            remove_btn.setToolTip(
                "Delete the follower's entity and its PlayerFollowers binding, "
                "freeing the slot for a different follower"
            )
            remove_btn.clicked.connect(
                lambda: self._remove_follower(
                    str(current_guid),
                    str(row.get("follower_name") or current_guid),
                    "follower",
                    str(row.get("name") or "?"),
                    dialog,
                )
            )
            layout.addWidget(current)
            layout.addWidget(remove_btn)
            layout.addSpacing(12)

        options = self._recruit_options()
        if not options:
            missing = QLabel(
                "No follower catalog available. The game's Followers.json / "
                "Characters.json were not found under the FTK2 install — launch "
                "the game once, then reopen the editor."
            )
            missing.setWordWrap(True)
            missing.setStyleSheet("color: #9aa3ad;")
            layout.addWidget(missing)
        elif current_guid:
            full = QLabel(
                "This hero already has a follower, so recruiting another is "
                "disabled. Remove the current one first."
            )
            full.setWordWrap(True)
            full.setStyleSheet("color: #9aa3ad;")
            layout.addWidget(full)
        else:
            recruit_label = QLabel("Recruit")
            recruit_label.setStyleSheet("color: #9aa3ad;")
            layout.addWidget(recruit_label)
            recruit_row = QHBoxLayout()
            combo = QComboBox()
            combo.setMinimumWidth(300)
            for option in options:
                kind_label = "Pet" if option["kind"] == "pet" else "Mercenary"
                low, high = min(option["tiers"]), max(option["tiers"])
                combo.addItem(
                    f"{option['class_name']}  ·  {kind_label}  ·  T{low}–{high}",
                    option,
                )
            recruit_row.addWidget(combo, 1)
            tier_label = QLabel("Tier")
            tier_label.setStyleSheet("color: #9aa3ad;")
            recruit_row.addWidget(tier_label)
            tier_spin = QSpinBox()
            tier_spin.setToolTip("Tier: 0 = base stats, 7 = max")
            tier_spin.setFixedWidth(80)
            recruit_row.addWidget(tier_spin)
            layout.addLayout(recruit_row)

            def _sync_tier_range() -> None:
                option = combo.currentData()
                tiers = option.get("tiers") if isinstance(option, dict) else None
                if not isinstance(tiers, list) or not tiers:
                    tier_spin.setRange(0, 7)
                    return
                low, high = int(min(tiers)), int(max(tiers))
                tier_spin.setRange(low, high)
                tier_spin.setValue(max(low, min(int(tier_spin.value()), high)))

            combo.activated.connect(_sync_tier_range)
            _sync_tier_range()

            add_btn = QPushButton("Recruit & save")
            add_btn.setDefault(True)
            add_btn.setToolTip(
                "Add the selected follower, bound to this hero via PlayerFollowers"
            )

            def _add() -> None:
                option = combo.currentData()
                if not isinstance(option, dict) or not option.get("class_name"):
                    QMessageBox.information(self, APP_TITLE, "Select a follower to recruit.")
                    return
                self._add_follower(
                    str(guid),
                    str(row.get("name") or "?"),
                    str(option["kind"]),
                    str(option["class_name"]),
                    int(tier_spin.value()),
                    dialog,
                )

            add_btn.clicked.connect(_add)
            layout.addWidget(add_btn)

        layout.addStretch(1)
        dialog.show()
        self._inventory_windows.append(dialog)

    def _add_follower(
        self,
        host_guid: str,
        host_name: str,
        kind: str,
        class_name: str,
        tier: int,
        dialog: QDialog,
    ) -> None:
        """Confirm, write and reload a new mercenary/pet bound to *host_guid*."""
        if not self._path:
            return
        is_pet = kind == "pet"
        spec = companion_spec(class_name, tier) if is_pet else mercenary_spec(class_name, tier)
        if spec is None:
            QMessageBox.critical(
                self,
                APP_TITLE,
                f"No character config found for {class_name} at tier {tier}.",
            )
            return
        extra = " The pet starts with 50 kibble." if is_pet else ""
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Recruit {class_name} (tier {tier}, {spec.get('config_name')}) "
            f"as a follower of {host_name}?\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.\n\n"
            "Stats come from the game's Characters.json; the follower spawns "
            f"beside the party on the current map.{extra}",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            data = self._path.read_bytes()
            if is_pet:
                modified, ok, _guid = add_pet(data, host_guid, spec)
            else:
                modified, ok, _guid = add_mercenary(data, host_guid, spec)
            if not ok:
                QMessageBox.critical(
                    self,
                    APP_TITLE,
                    "Could not add the follower (not a GameRun, unknown player, "
                    "invalid structure, or this hero already has a follower — "
                    "remove the current one first).",
                )
                return
            self._path.write_bytes(modified)
            label = "pet" if is_pet else "mercenary"
            self.statusBar().showMessage(
                f"Recruited {label} {class_name} (tier {tier}) for "
                f"{host_name} (backup {bak.name})"
            )
            self._pending_select_guid = host_guid
            dialog.close()
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def _remove_follower(
        self,
        follower_guid: str,
        follower_name: str,
        label: str,
        owner: str,
        dialog: QDialog,
    ) -> None:
        """Confirm, delete *follower_guid* and its binding, then reload."""
        if not self._path:
            return
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Remove the {label} {follower_name} from {owner}?\n\n"
            "This deletes the follower's entity and its PlayerFollowers binding, "
            "freeing the slot so you can recruit another.\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            data = self._path.read_bytes()
            modified, ok = remove_follower(data, follower_guid)
            if not ok:
                QMessageBox.critical(
                    self,
                    APP_TITLE,
                    "Could not remove that follower (not a GameRun, unknown "
                    "GUID, or not a removable follower).",
                )
                return
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Removed {label} {follower_name} (backup {bak.name})"
            )
            self._pending_select_guid = None
            dialog.close()
            self.load_path(self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, APP_TITLE, f"Save failed:\n{exc}")

    def apply_swap_class(self, new_class: str) -> None:
        if not self._path or not self._view or self._view.get("kind") != "run":
            QMessageBox.warning(
                self,
                APP_TITLE,
                "Open a GameRuns/*.ftk2 expedition save to swap a character's class.",
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
        if new_class not in self._playable_classes:
            QMessageBox.information(self, APP_TITLE, "Select a class from the list.")
            return
        old_class = str(row.get("class") or "?")
        if new_class == old_class:
            QMessageBox.information(
                self,
                APP_TITLE,
                f"{row.get('name')} is already that class.",
            )
            return
        reply = QMessageBox.question(
            self,
            APP_TITLE,
            f"Swap {row.get('name')}'s class from {old_class} to {new_class}?\n\n"
            f"File: {self._path}\n"
            "A .bak backup will be created. Quit the game first if it is running.\n\n"
            "Only CharacterComponent.ConfigName changes; current HP/gear/levels are kept.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            bak = backup(self._path)
            data = self._path.read_bytes()
            modified, ok = swap_character_class(data, str(guid), new_class)
            if not ok:
                QMessageBox.critical(
                    self,
                    APP_TITLE,
                    "Could not swap the class (not a GameRun or unknown character).",
                )
                return
            self._path.write_bytes(modified)
            self.statusBar().showMessage(
                f"Swapped {row.get('name')} class {old_class} -> {new_class} (backup {bak.name})"
            )
            self._pending_select_guid = str(guid)
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
