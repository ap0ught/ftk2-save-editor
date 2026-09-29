"""GUI tests for the Party action bar and the unified Followers dialog.

These run Qt offscreen (no display needed) and are hermetic: the save-candidate
and game-asset loaders are monkeypatched so the window never touches the real
For The King II install, and every save written comes from synthetic blobs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ftk2_editor import encrypt_ftk2_text
from ftk2_editor import gui as gui_mod

# Force the offscreen platform plugin: these tests build real widgets, and CI
# runners have no display.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QPushButton  # noqa: E402


# --- Synthetic save builders -------------------------------------------------


def _thing(config: str, count: int) -> dict:
    return {"ConfigName": config, "Type": "ITEM", "_stackCount": count}


def _hero(guid: str, name: str, class_name: str, gold: int) -> dict:
    return {
        "Guid": guid,
        "Components": {
            "CharacterComponent": {
                "DisplayName": name,
                "ConfigName": class_name,
                "CharacterType": "STANDARD",
                "CurrentHealth": 100,
                "CurrentFocus": 50,
                "State": "OK",
                "Things": [_thing("CURRENCY_ADVENTURE", gold), _thing("XP", 10)],
            },
            "PlayerComponent": {"IsLocal": True},
            "AdventureComponent": {"MapID": "map-town"},
        },
    }


def _follower(guid: str, name: str, config: str, ctype: str) -> dict:
    return {
        "Guid": guid,
        "Components": {
            "CharacterComponent": {
                "DisplayName": name,
                "ConfigName": config,
                "CharacterType": ctype,
                "CurrentHealth": 60,
                "CurrentFocus": 10,
                "Things": [],
            }
        },
    }


def _run_obj() -> dict:
    return {
        "Entities": [
            _hero("hero-1", "Alaric", "HUNTER", 250),
            _hero("hero-2", "Liora", "BLACKSMITH", 75),
            _follower("pet-1", "Sparky", "COMPANION_BAT_BASIC_06", "COMPANION"),
        ],
        "PlayerFollowers": {"hero-1": {"FollowerID": "pet-1", "RoundsToExpire": 1}},
        "Stats": {"GOLD_COLLECTED": 1000},
    }


def _user_obj() -> dict:
    return {
        "PartyCharacters": [_hero("hero-1", "Alaric", "HUNTER", 0), _hero("hero-2", "Liora", "BLACKSMITH", 0)],
        "LocalStats": {"TOTAL_LORE": 42},
    }


def _write_run(path: Path) -> None:
    summary = {"runID": "RUN-9ab2", "saveName": "Test run"}
    text = f"//**{json.dumps(summary)}**//\n" + json.dumps(_run_obj(), indent=2) + "\n"
    path.write_bytes(encrypt_ftk2_text(text))


def _write_user(path: Path) -> None:
    path.write_bytes(encrypt_ftk2_text(json.dumps(_user_obj(), indent=2) + "\n"))


def _json(blob: bytes) -> dict:
    from ftk2_editor import parse_ftk2

    return parse_ftk2(blob)["json"]


def _character(blob: bytes, guid: str) -> dict:
    """The CharacterComponent for *guid*, from a run blob or a User roster."""
    obj = _json(blob)
    entities = obj.get("Entities") or obj.get("PartyCharacters") or []
    for entity in entities:
        if entity.get("Guid") == guid:
            return entity["Components"]["CharacterComponent"]
    raise AssertionError(f"{guid} not found")


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    """A MainWindow wired to synthetic saves, with catalogs stubbed in."""
    run_path = tmp_path / "GameRuns" / "RUN-9ab2.ftk2"
    run_path.parent.mkdir()
    _write_run(run_path)
    _write_user(tmp_path / "User.ftk2")

    monkeypatch.setattr(gui_mod, "list_save_candidates", lambda: [])
    monkeypatch.setattr(gui_mod, "unique_saved_items", lambda: [])
    monkeypatch.setattr(gui_mod, "mercenary_catalog", lambda: [])
    monkeypatch.setattr(gui_mod, "playable_class_names", lambda: [])
    monkeypatch.setattr(gui_mod, "companion_catalog", lambda: [])

    win = gui_mod.MainWindow()

    # The window's own workers already ran against the stubs above; drive the
    # load synchronously so no QThread timing is involved in these assertions.
    def _load(path):
        win._path = Path(path)
        win._on_loaded(0, gui_mod.load_save_view(Path(path)))

    monkeypatch.setattr(win, "load_path", _load)
    win.load_path(run_path)
    yield win
    win.close()


def _select(window, row: dict) -> None:
    table = window.party_table
    table.setSortingEnabled(False)
    table.setRowCount(1)
    item = gui_mod.QTableWidgetItem(str(row.get("name")))
    item.setData(gui_mod.Qt.ItemDataRole.UserRole, row)
    table.setItem(0, 0, item)
    table.setSortingEnabled(True)
    table.selectRow(0)


HOST_ROW = {
    "guid": "hero-1",
    "name": "Alaric",
    "class": "HUNTER",
    "gold": 250,
    "has_player_component": True,
    "character_type": "STANDARD",
    "follower_guid": None,
    "follower_name": None,
    "follows_guid": None,
    "follows_name": None,
    "inventory": [],
}
HOST_WITH_PET = {**HOST_ROW, "follower_guid": "pet-1", "follower_name": "Sparky"}
PET_ROW = {
    "guid": "pet-1",
    "name": "Sparky",
    "class": "COMPANION_BAT_BASIC_06",
    "gold": None,
    "has_player_component": False,
    "character_type": "COMPANION",
    "follower_guid": None,
    "follower_name": None,
    "follows_guid": "hero-1",
    "follows_name": "Alaric",
    "inventory": [],
}


def _labels(dialog: QDialog) -> list[str]:
    return [w.text() for w in dialog.findChildren(QLabel)]


def _buttons(dialog: QDialog) -> list[str]:
    return [w.text() for w in dialog.findChildren(QPushButton)]


def _last_dialog(window) -> QDialog:
    return window._inventory_windows[-1]


# --- Action bar ---------------------------------------------------------------


def test_action_bar_is_a_single_row_of_few_controls(window):
    # One Apply covers gold + name; the old per-action buttons are gone.
    assert window.apply_btn.text() == "Apply & save"
    for gone in (
        "apply_gold_btn",
        "apply_all_gold_btn",
        "rename_btn",
        "wheel_piece_btn",
        "topup_party_btn",
        "topup_snacks_btn",
        "add_merc_btn",
        "add_pet_btn",
        "remove_follower_btn",
        "swap_class_btn",
    ):
        assert not hasattr(window, gone), gone


def test_more_menu_holds_the_party_wide_actions(window):
    labels = [a.text() for a in window.more_menu.actions() if a.text()]
    assert labels == [
        "Set gold for whole party",
        "Top up party consumables",
        "Top up party snacks to 10",
        "Give Carnival Wheel piece",
        "Create evil reflection…",
        "Give consumable to party…",
        "Fix invisible followers",
        "Swap class",
    ]


def _more_states(window) -> dict[str, bool]:
    return {a.text(): a.isEnabled() for a in window.more_menu.actions() if a.text()}


def test_party_wide_actions_survive_a_non_run_save(window, tmp_path):
    """Regression: the menu used to be disable-only, so opening a User save
    left every party-wide entry greyed out for good -- a GameRuns save loaded
    afterwards still showed a dead menu, with the button itself enabled."""
    run_path = tmp_path / "GameRuns" / "RUN-9ab2.ftk2"
    user_path = tmp_path / "User.ftk2"

    # 1. A non-run save switches everything off...
    window.load_path(user_path)
    assert not window.more_btn.isEnabled()
    assert not any(_more_states(window).values()), _more_states(window)

    # 2. ...and a run save must switch the selection-independent entries back
    #    on, with nothing selected in the party table.
    window.load_path(run_path)
    assert window.more_btn.isEnabled()
    states = _more_states(window)
    for label in (
        "Top up party consumables",
        "Top up party snacks to 10",
        "Fix invisible followers",
    ):
        assert states[label], label
    # ...while the ones that do need a selected character stay off.
    for label in ("Set gold for whole party", "Give Carnival Wheel piece", "Swap class"):
        assert not states[label], label

    # 3. Selecting a character enables those too, and the party-wide entries
    #    must not be disturbed by the selection changing.  "Swap class" stays
    #    off here because this fixture stubs the game-asset catalogs to empty.
    window.party_table.selectRow(0)
    states = _more_states(window)
    for label in (
        "Set gold for whole party",
        "Give Carnival Wheel piece",
        "Top up party consumables",
        "Top up party snacks to 10",
        "Fix invisible followers",
    ):
        assert states[label], label
    assert not states["Swap class"]


def test_class_submenu_is_a_popup_not_a_child_widget(window):
    """Regression: QMenu().setParent(w) drops the Qt.Popup flag, which turned
    the Swap class submenu into a child widget laid out at (0,0) inside the
    window -- it painted the whole class list over the party table and the
    action bar, and swallowed clicks on More actions."""
    from PySide6.QtCore import Qt

    menu = window._class_menu
    assert menu.isWindow(), "class submenu must be a top-level popup"
    assert menu.windowFlags() & Qt.WindowType.Popup
    # parented to the button, like more_menu
    assert menu.parent() is window.more_btn
    # a popup stays hidden until opened; the broken version was a live child
    # widget painted over the window
    assert not menu.isVisible()


def test_saves_sidebar_keeps_a_readable_width(window):
    """Regression: with no minimum the pane collapsed to its
    minimumSizeHint (112px), wrapping the save paths one character per line,
    and setSizes() during __init__ was discarded before the splitter had a
    geometry."""
    pane = window.save_list.parent()
    assert pane.minimumWidth() >= 280
    assert window.splitter is not None
    window.show()
    qt_app = QApplication.instance()
    if qt_app is not None:
        qt_app.processEvents()
    assert pane.width() >= 280
    assert window.splitter.sizes()[0] >= 280


def test_controls_start_disabled_until_a_character_is_selected(window):
    assert not window.apply_btn.isEnabled()
    assert not window.followers_btn.isEnabled()
    _select(window, HOST_ROW)
    assert window.apply_btn.isEnabled()


def test_evil_reflection_needs_a_selected_hero(window):
    """Unlike the party-wide tools, mirroring is per-hero."""
    assert not window._action_evil_reflection.isEnabled()
    _select(window, HOST_ROW)
    assert window._action_evil_reflection.isEnabled()
    assert window.followers_btn.isEnabled()
    assert window.more_btn.isEnabled()


def test_class_swap_submenu_is_built_from_the_playable_catalog(window):
    window._playable_classes = ["HUNTER", "MONK"]
    window._rebuild_class_menu()
    assert [a.text() for a in window._class_menu.actions()] == ["HUNTER", "MONK"]


def test_loading_a_new_save_without_a_selection_re_disables_the_bar(window, tmp_path):
    # Party-wide tools in More actions work with no selection, but the inline
    # fields must not stay live from a previous run save once a User save loads.
    _select(window, HOST_ROW)
    assert window.more_btn.isEnabled()
    user_path = tmp_path / "User.ftk2"
    window.load_path(user_path)
    assert not window.apply_btn.isEnabled()
    assert not window.followers_btn.isEnabled()
    assert not window.more_btn.isEnabled()


# --- Followers dialog ---------------------------------------------------------


def test_followers_dialog_lists_mercs_and_pets_in_one_combo(window, monkeypatch):
    monkeypatch.setattr(
        window,
        "_mercenaries",
        [{"class_name": "MERC_ARCHER", "tiers": [0, 1, 2, 3]}],
    )
    monkeypatch.setattr(
        window,
        "_companions",
        [{"class_name": "COMPANION_BAT", "tiers": [0, 7]}],
    )
    _select(window, HOST_ROW)
    window.open_followers_dialog()
    dialog = _last_dialog(window)
    combos = dialog.findChildren(QComboBox)
    assert len(combos) == 1, "mercs and pets must share one dropdown"
    entries = [combos[0].itemText(i) for i in range(combos[0].count())]
    assert entries == [
        "MERC_ARCHER  ·  Mercenary  ·  T0–3",
        "COMPANION_BAT  ·  Pet  ·  T0–7",
    ]
    assert "Recruit & save" in _buttons(dialog)


def test_followers_dialog_tier_spin_follows_the_selected_entry(window, monkeypatch):
    monkeypatch.setattr(
        window, "_mercenaries", [{"class_name": "MERC_ARCHER", "tiers": [2, 3, 4]}]
    )
    monkeypatch.setattr(window, "_companions", [])
    _select(window, HOST_ROW)
    window.open_followers_dialog()
    dialog = _last_dialog(window)
    tier_spin = dialog.findChildren(QComboBox)[0]
    spins = [w for w in dialog.children() if w.__class__.__name__ == "QSpinBox"]
    assert spins, "tier control missing"
    assert (spins[0].minimum(), spins[0].maximum()) == (2, 4)
    assert tier_spin.count() == 1


def test_followers_dialog_offers_removal_from_the_host_row(window):
    _select(window, HOST_WITH_PET)
    window.open_followers_dialog()
    dialog = _last_dialog(window)
    assert not dialog.findChildren(QComboBox), "no recruiting while the slot is full"
    assert "Remove follower & save" in _buttons(dialog)
    assert any("Sparky" in text for text in _labels(dialog))


def test_followers_dialog_on_a_follower_row_only_offers_removal(window):
    _select(window, PET_ROW)
    window.open_followers_dialog()
    dialog = _last_dialog(window)
    assert not dialog.findChildren(QComboBox)
    assert _buttons(dialog) == ["Remove this pet & save"]
    assert any("Alaric" in text for text in _labels(dialog))


def test_followers_dialog_explains_a_missing_catalog(window):
    _select(window, HOST_ROW)
    window.open_followers_dialog()
    dialog = _last_dialog(window)
    assert not dialog.findChildren(QComboBox)
    assert any("catalog" in text for text in _labels(dialog))


# --- Merged apply -------------------------------------------------------------


def test_apply_writes_gold_and_name_in_one_go(window, monkeypatch, tmp_path):
    monkeypatch.setattr(
        gui_mod.QMessageBox, "question", lambda *a, **k: gui_mod.QMessageBox.StandardButton.Yes
    )
    _select(window, {**HOST_ROW, "gold": 250})
    window.gold_spin.setValue(1234)
    window.name_edit.setText("Alaric the Bold")
    window.apply_selected()

    run_path = window._path
    character = _character(run_path.read_bytes(), "hero-1")
    assert character["DisplayName"] == "Alaric the Bold"
    wallet = [t for t in character["Things"] if t["ConfigName"] == "CURRENCY_ADVENTURE"]
    assert wallet[0]["_stackCount"] == 1234
    # The campaign roster in User.ftk2 must agree with the run.
    user_blob = (tmp_path / "User.ftk2").read_bytes()
    roster = _character(user_blob, "hero-1")
    assert roster["DisplayName"] == "Alaric the Bold"
    assert list(tmp_path.glob("*.bak")), "a backup should exist"


def test_apply_reports_when_nothing_changed(window, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        gui_mod.QMessageBox, "information", lambda *a, **k: shown.append(a[-1])
    )
    _select(window, {**HOST_ROW, "gold": 250})
    window.gold_spin.setValue(250)
    window.name_edit.setText("Alaric")
    window.apply_selected()
    assert shown and "Nothing to apply" in shown[0]


def test_removing_a_follower_deletes_entity_and_binding(window, monkeypatch):
    monkeypatch.setattr(
        gui_mod.QMessageBox, "question", lambda *a, **k: gui_mod.QMessageBox.StandardButton.Yes
    )
    _select(window, HOST_WITH_PET)
    window.open_followers_dialog()
    dialog = _last_dialog(window)
    remove = [b for b in dialog.findChildren(QPushButton) if b.text().startswith("Remove")][0]
    remove.click()

    run = _json(window._path.read_bytes())
    assert "pet-1" not in {e.get("Guid") for e in run["Entities"]}
    # The host's binding is gone, so the follower slot is free again.
    assert "pet-1" not in {
        info.get("FollowerID") for info in (run.get("PlayerFollowers") or {}).values()
    }
