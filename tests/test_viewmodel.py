"""Tests for save view helpers used by the GUI.

These tests are deliberately hermetic: they build synthetic User and GameRun
saves, encrypt them into real ``.ftk2`` bytes, and monkeypatch the module-level
``USER_SAVE`` / ``GAME_RUNS_DIR`` path bindings to point at a tmp dir. Nothing
here reads Christopher's actual game save, so the suite passes regardless of
the local save state and on CI runners with no game installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ftk2_editor import encrypt_ftk2_text
from ftk2_editor import viewmodel as vm


# --- Synthetic save builders -------------------------------------------------


def _wallet_thing(config: str, count: int) -> dict:
    """A CharacterComponent.Things entry for a currency/XP stack."""
    return {"ConfigName": config, "Type": "ITEM", "_stackCount": count}


def _party_entity(guid: str, name: str, class_name: str, gold: int, xp: int) -> dict:
    """A player character entity that will land in the Party tab."""
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
                "Things": [
                    _wallet_thing("CURRENCY_ADVENTURE", gold),
                    _wallet_thing("XP", xp),
                    _wallet_thing("HERB_HEALING", 5),
                ],
            },
            "PlayerComponent": {"IsLocal": True},
            "AdventureComponent": {"MapID": "map-town"},
        },
    }


def _enemy_entity(guid: str, name: str) -> dict:
    """A non-player entity used to populate the Non-Party tab."""
    return {
        "Guid": guid,
        "Components": {
            "CharacterComponent": {
                "DisplayName": name,
                "ConfigName": "GOBLIN",
                "CharacterType": "STANDARD",
                "CurrentHealth": 20,
                "CurrentFocus": 0,
                "Things": [],
            }
        },
    }


def _make_run() -> dict:
    return {
        "Entities": [
            _party_entity("hero-1", "Alaric", "HUNTER", gold=250, xp=120),
            _party_entity("hero-2", "Liora", "BLACKSMITH", gold=75, xp=90),
            _enemy_entity("enemy-1", "Goblin"),
        ],
        "Stats": {"GOLD_COLLECTED": 1000, "GOLD_SPENT": 400},
        "HouseRules": {"RULES_HERB_SALVAGE": True},
        "GameDifficulty": "Apprentice",
        "ConfigName": "adventure_small_lands",
    }


def _make_user() -> dict:
    return {
        "PartyCharacters": [
            _party_entity("hero-1", "Alaric", "HUNTER", gold=0, xp=0),
            _party_entity("hero-2", "Liora", "BLACKSMITH", gold=0, xp=0),
        ],
        "LocalStats": {"TOTAL_LORE": 42, "GOLD_COLLECTED": 1000, "GOLD_SPENT": 400},
        "NewLoreStoreUnlocks": ["SKIN_HELMET_LUCKY"],
        "LastPlayedVersionString": "1.14.6",
        "LastUsedDifficulty": "Apprentice",
        "LastGameRunIdPlayed": "RUN-9ab2",
        "Language": "en",
    }


def _write_ftk2(path: Path, obj: dict, *, run: bool = False) -> None:
    """Encrypt a synthetic save dict to a real ``.ftk2`` file."""
    if run:
        summary = {
            "runID": "RUN-9ab2",
            "saveName": "Test run",
            "difficulty": "Apprentice",
        }
        text = f"//**{json.dumps(summary)}**//\n" + json.dumps(obj, indent=2) + "\n"
    else:
        text = json.dumps(obj, indent=2) + "\n"
    path.write_bytes(encrypt_ftk2_text(text))


@pytest.fixture
def save(tmp_path: Path, monkeypatch):
    """Write synthetic User + GameRun saves to a tmp dir and patch viewmodel paths."""
    runs_dir = tmp_path / "GameRuns"
    runs_dir.mkdir()
    user_path = tmp_path / "User.ftk2"
    run_path = runs_dir / "RUN-9ab2.ftk2"

    _write_ftk2(user_path, _make_user())
    _write_ftk2(run_path, _make_run(), run=True)

    monkeypatch.setattr(vm, "USER_SAVE", user_path)
    monkeypatch.setattr(vm, "GAME_RUNS_DIR", runs_dir)
    return {"user": user_path, "runs": runs_dir, "run": run_path}


# --- Tests ---------------------------------------------------------------------


def test_list_save_candidates_excludes_user(save):
    paths = [c["path"] for c in vm.list_save_candidates()]
    assert save["user"] not in paths
    assert save["run"] in paths


def test_load_user_view(save):
    view = vm.load_save_view(save["user"])
    assert view["kind"] == "user"
    assert view["overview"]["lore"] == 42
    assert isinstance(view["party"], list)


def test_load_active_run_party_gold(save):
    user = vm.load_save_view(save["user"])
    run_id = user["overview"]["last_run"]
    run_path = save["runs"] / f"{run_id}.ftk2"
    assert run_path.exists()
    view = vm.load_save_view(run_path)
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


def test_party_from_run_helper(save):
    run = vm.load_save_view(save["run"])
    party = vm.party_from_run(run["raw"]["json"])
    assert len(party) >= 1
