"""Tests for save view helpers used by the GUI."""

from __future__ import annotations

from ftk2_editor import USER_SAVE, GAME_RUNS_DIR
from ftk2_editor.viewmodel import load_save_view, list_save_candidates, party_from_run


def test_list_save_candidates_excludes_user():
    paths = [c["path"] for c in list_save_candidates()]
    assert USER_SAVE not in paths


def test_load_user_view():
    view = load_save_view(USER_SAVE)
    assert view["kind"] == "user"
    assert view["overview"]["lore"] is not None
    assert isinstance(view["party"], list)


def test_load_active_run_party_gold():
    user = load_save_view(USER_SAVE)
    run_id = user["overview"]["last_run"]
    run_path = GAME_RUNS_DIR / f"{run_id}.ftk2"
    assert run_path.exists()
    view = load_save_view(run_path)
    assert view["kind"] == "run"
    assert "house_rules" in view["overview"]
    assert isinstance(view.get("non_party"), list)
    assert all(
        row.get("has_player_component") is True
        or row.get("character_type") == "COMPANION"
        for row in view.get("party", [])
    )
    assert all(
        (row.get("character_type") in (None, "STANDARD"))
        for row in view.get("party", [])
    )
    assert view["overview"]["party_gold_total"] is not None
    assert any(row.get("gold") is not None for row in view["party"])


def test_party_from_run_helper():
    user = load_save_view(USER_SAVE)
    run = load_save_view(GAME_RUNS_DIR / f"{user['overview']['last_run']}.ftk2")
    party = party_from_run(run["raw"]["json"])
    assert len(party) >= 1
