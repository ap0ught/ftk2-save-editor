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


def _follower_entity(guid: str, name: str, config: str, ctype: str) -> dict:
    """A COMPANION/MERCENARY entity referenced by PlayerFollowers."""
    return {
        "Guid": guid,
        "Components": {
            "CharacterComponent": {
                "DisplayName": name,
                "ConfigName": config,
                "CharacterType": ctype,
                "CurrentHealth": 60,
                "CurrentFocus": 10,
                "Things": [_wallet_thing("HERB_HEALING", 3)],
            }
        },
    }


def _make_run() -> dict:
    return {
        "Entities": [
            _party_entity("hero-1", "Alaric", "HUNTER", gold=250, xp=120),
            _party_entity("hero-2", "Liora", "BLACKSMITH", gold=75, xp=90),
            _enemy_entity("enemy-1", "Goblin"),
            _follower_entity("follower-1", "Sparky", "COMPANION_BAT_BASIC_06", "COMPANION"),
            _follower_entity("follower-2", "Bolt", "MERC_ARCHER_BASIC_03", "MERCENARY"),
        ],
        "PlayerFollowers": {
            "hero-1": {"FollowerID": "follower-1", "RoundsToExpire": 1},
            "hero-2": {"FollowerID": "follower-2", "RoundsToExpire": 0},
        },
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
        or row.get("character_type") in ("COMPANION", "MERCENARY")
        for row in view.get("party", [])
    )
    assert all(
        (row.get("character_type") in (None, "STANDARD"))
        or row.get("character_type") in ("COMPANION", "MERCENARY")
        for row in view.get("party", [])
    )
    assert view["overview"]["party_gold_total"] is not None
    assert any(row.get("gold") is not None for row in view["party"])


def test_party_from_run_helper(save):
    run = vm.load_save_view(save["run"])
    party = vm.party_from_run(run["raw"]["json"])
    assert len(party) >= 1


def test_unique_saved_items_unions_user_and_all_main_runs(save):
    user = _make_user()
    user["PartyCharacters"][0]["Components"]["CharacterComponent"]["Things"].append(
        {
            "ConfigName": "STAFF_HOME_01",
            "Type": "EQUIPMENT",
            "_stackCount": 1,
            "Expansion": "LORE_STORE",
        }
    )
    _write_ftk2(save["user"], user)

    fire_run = _make_run()
    fire_run["Entities"][0]["Components"]["CharacterComponent"]["Things"].append(
        {"ConfigName": "BOW_FIRE_01", "Type": "EQUIPMENT", "_stackCount": 1}
    )
    _write_ftk2(save["runs"] / "RUN-fire.ftk2", fire_run, run=True)

    items = vm.unique_saved_items()

    by_config = {item["config"]: item["type"] for item in items}
    assert by_config["STAFF_HOME_01"] == "EQUIPMENT"
    assert by_config["BOW_FIRE_01"] == "EQUIPMENT"
    assert next(item for item in items if item["config"] == "STAFF_HOME_01")[
        "expansion"
    ] == "LORE_STORE"
    assert [item["config"] for item in items].count("STAFF_HOME_01") == 1


def test_replacement_item_configs_filters_by_type_and_config_family():
    catalog = [
        {"config": "BOW_FIRE_MEDIUM_01", "type": "EQUIPMENT"},
        {"config": "BLUNT_SHOVEL_HEAVY_00", "type": "EQUIPMENT"},
        {"config": "HERB_GODSBEARD", "type": "ITEM"},
    ]
    selected = {"config": "BOW_MILITIA_MEDIUM_00", "type": "EQUIPMENT"}

    assert vm.replacement_item_configs(catalog, selected, same_type=True) == [
        "BOW_FIRE_MEDIUM_01"
    ]
    assert vm.replacement_item_configs(catalog, selected, same_type=False) == [
        "BLUNT_SHOVEL_HEAVY_00",
        "BOW_FIRE_MEDIUM_01",
        "HERB_GODSBEARD",
    ]
    assert vm.replacement_item_configs(catalog, {}, same_type=False) == [
        "BLUNT_SHOVEL_HEAVY_00",
        "BOW_FIRE_MEDIUM_01",
        "HERB_GODSBEARD",
    ]


def test_run_display_name_uses_save_name(save):
    assert vm.run_display_name(save["run"]) == "Test run"


def test_run_display_name_falls_back_to_filename(tmp_path):
    missing = tmp_path / "not-a-parseable.ftk2"
    missing.write_text("garbage")
    assert vm.run_display_name(missing) == "not-a-parseable.ftk2"


def test_followers_surface_in_party(save):
    view = vm.load_save_view(save["run"])
    guids = {row.get("guid") for row in view["party"]}
    # Both COMPANION and MERCENARY followers referenced by PlayerFollowers
    # must appear alongside the main heroes, not in non_party.
    assert "follower-1" in guids
    assert "follower-2" in guids
    assert any(row.get("character_type") == "COMPANION" for row in view["party"])
    assert any(row.get("character_type") == "MERCENARY" for row in view["party"])
    np_guids = {row.get("guid") for row in view["non_party"]}
    assert "follower-1" not in np_guids
    assert "follower-2" not in np_guids
    # Player-controlled party members carry this flag; followers do not.
    assert any(row.get("has_player_component") for row in view["party"])
    assert any(
        not row.get("has_player_component")
        and row.get("character_type") in ("COMPANION", "MERCENARY")
        for row in view["party"]
    )


def test_pet_owners_are_player_hosts_with_companion_followers(save):
    view = vm.load_save_view(save["run"])
    # hero-1's follower is a COMPANION; hero-2's is a MERCENARY.
    assert view["pet_owners"] == {"hero-1"}


def test_pet_owners_empty_for_user_save(save):
    view = vm.load_save_view(save["user"])
    assert view["pet_owners"] == set()


def test_malformed_player_followers_shape_is_ignored(save):
    run = _make_run()
    run["PlayerFollowers"] = ["not", "a", "mapping"]
    _write_ftk2(save["run"], run, run=True)

    view = vm.load_save_view(save["run"])

    assert all(
        row.get("guid") not in {"follower-1", "follower-2"}
        for row in view["party"]
    )


def test_party_rows_carry_follower_bindings(save):
    view = vm.load_save_view(save["run"])
    by = {row["guid"]: row for row in view["party"]}
    assert by["hero-1"]["follower_guid"] == "follower-1"
    assert by["hero-1"]["follower_name"] == "Sparky"
    assert by["hero-2"]["follower_guid"] == "follower-2"
    assert by["follower-1"]["follows_guid"] == "hero-1"
    assert by["follower-1"]["follows_name"] == "Alaric"
    assert by["follower-2"]["follows_guid"] == "hero-2"
    assert by["follower-2"]["follows_name"] == "Liora"
    assert by["hero-1"]["follows_guid"] is None
    assert view["followers"] == {
        "hero-1": "follower-1",
        "hero-2": "follower-2",
    }


def test_view_followers_empty_for_user_save(save):
    view = vm.load_save_view(save["user"])
    assert view["followers"] == {}


def test_party_from_entities_deduplicates_by_guid_not_name():
    """Two different entities with the same DisplayName must both appear."""
    entities = [
        {
            "Guid": "follower-a",
            "Components": {
                "CharacterComponent": {
                    "DisplayName": "Ally",
                    "ConfigName": "COMP_01",
                    "CharacterType": "COMPANION",
                    "Things": [],
                },
                "PlayerComponent": {},
            },
        },
        {
            "Guid": "follower-b",
            "Components": {
                "CharacterComponent": {
                    "DisplayName": "Ally",
                    "ConfigName": "COMP_02",
                    "CharacterType": "COMPANION",
                    "Things": [],
                },
                "PlayerComponent": {},
            },
        },
    ]
    party = vm.party_from_entities(
        entities,
        standard_only=False,
        player_only=True,
        include_companions=True,
    )
    guids = {row["guid"] for row in party}
    assert guids == {"follower-a", "follower-b"}
    # Both have the same name but distinct GUIDs
    assert len(party) == 2


# --- Asset-catalog helpers ----------------------------------------------------


@pytest.fixture
def assets(tmp_path: Path, monkeypatch):
    """Synthetic Followers.json + Characters.json behind a patched assets dir."""
    assets_dir = tmp_path / "Assets"
    assets_dir.mkdir()
    followers = {
        "MERC_ARCHER_01": {
            "Type": "MERCENARY",
            "ConfigName": "MERC_ARCHER_BASIC_00",
            "ContractRounds": 8,
            "Rarity": "COMMON",
        },
        "MERC_GUN_01": {
            "Type": "MERCENARY",
            "ConfigName": "MERC_GUN_BASIC_00",
            "ContractRounds": 6,
            "Rarity": "RARE",
        },
        "NOT_A_FOLLOWER": {"Type": "TRAINING_DUMMY", "ConfigName": "MISC_X"},
        "BAD_ENTRY": "just-a-string",
    }
    characters = {
        "MERC_ARCHER_BASIC_00": {"Tags": ["MERCENARY"], "Stats": {"HP": 80, "FOC": 20}, "Things": {"BOW_ARCHER_TINY_00": 1, "QUIVER_BASIC_00": 1}},
        "MERC_ARCHER_BASIC_03": {"Tags": ["MERCENARY"], "Stats": {"HP": 105, "FOC": 20}, "Things": {"BOW_ARCHER_TINY_03": 1}},
        "MERC_GUN_BASIC_00": {"Tags": ["MERCENARY"], "Stats": {"HP": 90}, "Things": {}},
        "MERC_GUN_BASIC_06": {"Tags": ["MERCENARY"], "Stats": {"HP": 120}, "Things": {"GUN_MILITIA_TINY_03": 1}},
        "ALCHEMIST": {"Tags": ["PLAYER"], "Stats": {"HP": 60}, "Things": {}, "Passives": ["SKILL_PARTYHEAL"]},
        "BLACKSMITH": {"Tags": ["PLAYER"], "Stats": {"HP": 75}, "Things": {}, "Passives": ["SKILL_MEND"]},
        "HUNTER": {"Tags": ["PLAYER", "STARTER"], "Stats": {"HP": 70}, "Things": {}, "Passives": ["SKILL_MEDIC"]},
        "SPIDER": {"Tags": ["ENEMY"], "Stats": {"HP": 30}, "Things": {}},
    }
    (assets_dir / "Followers.json").write_text(json.dumps(followers))
    (assets_dir / "Characters.json").write_text(json.dumps(characters))
    monkeypatch.setattr(vm, "FTK2_ASSETS_DIR", assets_dir)
    vm._asset_cache.clear()
    return assets_dir


def test_mercenary_catalog_lists_only_mercenary_families(assets):
    catalog = vm.mercenary_catalog()
    names = [row["class_name"] for row in catalog]
    assert names == ["MERC_ARCHER_01", "MERC_GUN_01"]
    archer = catalog[0]
    assert archer["config_base"] == "MERC_ARCHER_BASIC_00"
    assert archer["contract_rounds"] == 8
    assert archer["rarity"] == "COMMON"
    assert archer["tiers"] == [0, 3]  # only the levels present in Characters.json


def test_mercenary_spec_builds_config_for_known_tier(assets):
    spec = vm.mercenary_spec("MERC_GUN_01", 6)
    assert spec is not None
    assert spec["config_name"] == "MERC_GUN_BASIC_06"
    assert spec["contract_rounds"] == 6
    assert spec["start_health"] == 120
    assert spec["type_args"] == "MERC_GUN_01"
    assert spec["start_things"] == ["GUN_MILITIA_TINY_03"]


def test_mercenary_spec_missing_tier_returns_none(assets):
    assert vm.mercenary_spec("MERC_GUN_01", 4) is None
    assert vm.mercenary_spec("MERC_ARCHER_01", 7) is None


def test_mercenary_spec_unknown_class_returns_none(assets):
    assert vm.mercenary_spec("MERC_GHOST_01", 0) is None
    assert vm.mercenary_spec("NOT_A_FOLLOWER", 0) is None


def test_merc_catalog_empty_when_assets_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "FTK2_ASSETS_DIR", tmp_path / "nope")
    vm._asset_cache.clear()
    assert vm.mercenary_catalog() == []
    assert vm.mercenary_spec("MERC_GUN_01", 0) is None
    assert vm.playable_class_names() == []


def test_playable_class_names_returns_player_tagged_sorted(assets):
    assert vm.playable_class_names() == ["ALCHEMIST", "BLACKSMITH", "HUNTER"]


def test_healer_class_names_uses_partyheal_or_medic_passives(assets):
    # ALCHEMIST has SKILL_PARTYHEAL, HUNTER has SKILL_MEDIC; BLACKSMITH's
    # SKILL_MEND is not a party heal and must not qualify.
    assert vm.healer_class_names() == {"ALCHEMIST", "HUNTER"}


def test_healer_class_names_empty_when_assets_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "FTK2_ASSETS_DIR", tmp_path / "nope")
    vm._asset_cache.clear()
    assert vm.healer_class_names() == set()


def test_companion_catalog_lists_resolvable_families(assets):
    # companions need a Followers.json with COMPANION entries; reuse the same
    # assets dir by adding companion rows to it.
    followers = {
        "COMPANION_RAT_01": {"Type": "COMPANION", "ConfigName": "COMPANION_RAT_BASIC_00", "ContractRounds": 0, "Rarity": "COMMON"},
        "COMPANION_WOLF_02": {"Type": "COMPANION", "ConfigName": "COMPANION_WOLF_SPECIAL_00", "ContractRounds": 0, "Rarity": "RARE"},
        "COMPANION_REFLECTION": {"Type": "COMPANION", "ConfigName": None},
    }
    characters_new = {
        "COMPANION_RAT_BASIC_00": {"Tags": ["COMPANION"], "Stats": {"HP": 80}, "Things": {}},
        "COMPANION_RAT_BASIC_03": {"Tags": ["COMPANION"], "Stats": {"HP": 95}, "Things": {}},
        "COMPANION_WOLF_SPECIAL_00": {"Tags": ["COMPANION"], "Stats": {"HP": 90}, "Things": {}},
        "COMPANION_WOLF_SPECIAL_07": {"Tags": ["COMPANION"], "Stats": {"HP": 115}, "Things": {}},
        "ALCHEMIST": {"Tags": ["PLAYER"], "Stats": {"HP": 60}, "Things": {}},
        "BLACKSMITH": {"Tags": ["PLAYER"], "Stats": {"HP": 75}, "Things": {}},
        "HUNTER": {"Tags": ["PLAYER", "STARTER"], "Stats": {"HP": 70}, "Things": {}},
        "SPIDER": {"Tags": ["ENEMY"], "Stats": {"HP": 30}, "Things": {}},
    }
    (assets / "Followers.json").write_text(json.dumps(followers))
    (assets / "Characters.json").write_text(json.dumps(characters_new))
    vm._asset_cache.clear()

    catalog = vm.companion_catalog()
    names = [row["class_name"] for row in catalog]
    assert names == ["COMPANION_RAT_01", "COMPANION_WOLF_02"]  # REFLECTION skipped
    wolf = catalog[1]
    assert wolf["config_base"] == "COMPANION_WOLF_SPECIAL_00"
    assert wolf["tiers"] == [0, 7]


def test_companion_spec_builds_config_for_known_tier(assets):
    followers = {
        "COMPANION_WOLF_01": {"Type": "COMPANION", "ConfigName": "COMPANION_WOLF_BASIC_00", "ContractRounds": 0, "Rarity": "COMMON"},
    }
    characters_new = {
        "COMPANION_WOLF_BASIC_00": {"Tags": ["COMPANION"], "Stats": {"HP": 80}, "Things": {}},
        "COMPANION_WOLF_BASIC_06": {"Tags": ["COMPANION"], "Stats": {"HP": 96}, "Things": {}},
        "ALCHEMIST": {"Tags": ["PLAYER"], "Stats": {"HP": 60}, "Things": {}},
        "BLACKSMITH": {"Tags": ["PLAYER"], "Stats": {"HP": 75}, "Things": {}},
        "HUNTER": {"Tags": ["PLAYER", "STARTER"], "Stats": {"HP": 70}, "Things": {}},
        "SPIDER": {"Tags": ["ENEMY"], "Stats": {"HP": 30}, "Things": {}},
    }
    (assets / "Followers.json").write_text(json.dumps(followers))
    (assets / "Characters.json").write_text(json.dumps(characters_new))
    vm._asset_cache.clear()

    spec = vm.companion_spec("COMPANION_WOLF_01", 6)
    assert spec is not None
    assert spec["config_name"] == "COMPANION_WOLF_BASIC_06"
    assert spec["contract_rounds"] == 0
    assert spec["start_health"] == 96
    assert spec["start_focus"] == 1  # companions carry 1 focus
    assert spec["type_args"] == "COMPANION_WOLF_01"
    assert spec["start_things"] == []


def test_companion_spec_missing_tier_returns_none(assets):
    followers = {
        "COMPANION_WOLF_01": {"Type": "COMPANION", "ConfigName": "COMPANION_WOLF_BASIC_00", "ContractRounds": 0, "Rarity": "COMMON"},
    }
    characters_new = {
        "COMPANION_WOLF_BASIC_00": {"Tags": ["COMPANION"], "Stats": {"HP": 80}, "Things": {}},
        "COMPANION_WOLF_BASIC_06": {"Tags": ["COMPANION"], "Stats": {"HP": 96}, "Things": {}},
        "ALCHEMIST": {"Tags": ["PLAYER"], "Stats": {"HP": 60}, "Things": {}},
        "BLACKSMITH": {"Tags": ["PLAYER"], "Stats": {"HP": 75}, "Things": {}},
        "HUNTER": {"Tags": ["PLAYER", "STARTER"], "Stats": {"HP": 70}, "Things": {}},
        "SPIDER": {"Tags": ["ENEMY"], "Stats": {"HP": 30}, "Things": {}},
    }
    (assets / "Followers.json").write_text(json.dumps(followers))
    (assets / "Characters.json").write_text(json.dumps(characters_new))
    vm._asset_cache.clear()

    assert vm.companion_spec("COMPANION_WOLF_01", 4) is None
    assert vm.companion_spec("COMPANION_GHOST_01", 0) is None


def test_companion_catalog_empty_when_assets_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "FTK2_ASSETS_DIR", tmp_path / "nope")
    vm._asset_cache.clear()
    assert vm.companion_catalog() == []
    assert vm.companion_spec("COMPANION_WOLF_01", 0) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
