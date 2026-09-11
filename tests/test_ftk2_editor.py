"""Tests for the FTK2 save editor (XOR-encrypted JSON)."""

from __future__ import annotations

import json

import pytest
import ftk2_editor as editor

from ftk2_editor import (
    ENCRYPT_KEY,
    backup,
    carry_over_consumables,
    decrypt_ftk2_bytes,
    dump_summary,
    dump_user_json,
    edit_field,
    ensure_character_herb_tool_minimum,
    ensure_party_herb_tool_minimum,
    ensure_party_food_minimum,
    encrypt_ftk2_text,
    parse_ftk2,
    rename_party_member,
    rename_party_member_synced,
    replace_character_thing,
    give_carnival_wheel_piece,
    set_carnival_tickets,
    verify_save,
    xor_crypt,
)


@pytest.fixture
def sample_user_obj() -> dict:
    return {
        "PartyCharacters": [],
        "LocalStats": {"LANG_ID": 1, "TOTAL_LORE": 42},
        "NewLoreStoreUnlocks": ["SKIN_HELMET_LUCKY"],
        "LastPlayedVersionString": "1.14.6",
        "Language": "en",
    }


@pytest.fixture
def sample_save_bytes(sample_user_obj) -> bytes:
    # Match game-ish CRLF indented JSON
    text = json.dumps(sample_user_obj, indent=2).replace("\n", "\r\n") + "\r\n"
    return encrypt_ftk2_text(text)


@pytest.fixture
def sample_run_bytes() -> bytes:
    summary = {
        "runID": "run-123",
        "saveName": "Test Expedition",
        "difficulty": "normal",
    }
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Hero",
                        "ConfigName": "HUNTER",
                        "Things": [
                            {
                                "ConfigName": "HERB_HEALING",
                                "Type": "ITEM",
                                "_stackCount": 2,
                            },
                            {
                                "ConfigName": "TOOL_LOCKPICK",
                                "Type": "ITEM",
                                "_stackCount": 1,
                            },
                            {
                                "ConfigName": "DRINK_ALE",
                                "Type": "ITEM",
                                "_stackCount": 4,
                            },
                            {
                                "ConfigName": "POTION_SPEED",
                                "Type": "ITEM",
                                "_stackCount": 3,
                            },
                        ],
                    }
                },
            }
        ]
    }
    text = f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n"
    return encrypt_ftk2_text(text)


def test_xor_is_symmetric():
    plain = '{"hello":123}'
    assert xor_crypt(xor_crypt(plain)) == plain
    assert ENCRYPT_KEY == "21398xa2"


def test_encrypt_decrypt_roundtrip(sample_user_obj):
    text = json.dumps(sample_user_obj, indent=2) + "\n"
    blob = encrypt_ftk2_text(text)
    assert blob.startswith(b"\xef\xbb\xbf")
    assert json.loads(decrypt_ftk2_bytes(blob)) == sample_user_obj


def test_verify_save_valid(sample_save_bytes):
    result = verify_save(sample_save_bytes)
    assert result["has_bom"] is True
    assert result["decrypts_to_json"] is True
    assert result["valid"] is True


def test_verify_save_missing_bom():
    result = verify_save(b"GARBAGE_DATA_NO_BOM")
    assert result["has_bom"] is False
    assert any("BOM" in issue for issue in result["issues"])


def test_parse_ftk2_returns_json(sample_save_bytes, sample_user_obj):
    result = parse_ftk2(sample_save_bytes)
    assert result["json"]["LocalStats"]["TOTAL_LORE"] == 42
    assert result["json"]["Language"] == sample_user_obj["Language"]


def test_dump_summary(sample_save_bytes):
    summary = dump_summary(parse_ftk2(sample_save_bytes))
    assert "FTK2 Save File Summary" in summary
    assert "LocalStats" in summary


def test_edit_local_stat(sample_save_bytes):
    modified, ok = edit_field(sample_save_bytes, "LocalStats.TOTAL_LORE", "999")
    assert ok
    obj = parse_ftk2(modified)["json"]
    assert obj["LocalStats"]["TOTAL_LORE"] == 999


def test_edit_top_level(sample_save_bytes):
    modified, ok = edit_field(sample_save_bytes, "Language", '"fr"')
    assert ok
    assert parse_ftk2(modified)["json"]["Language"] == "fr"


def test_backup_creates_file(tmp_path):
    test_file = tmp_path / "test_save.ftk2"
    test_file.write_bytes(b"test save data content")
    bak = backup(test_file)
    assert bak.exists()
    assert bak.read_bytes() == test_file.read_bytes()


def test_ensure_character_herb_tool_minimum_updates_matching_items(sample_run_bytes):
    modified, ok, updated = ensure_character_herb_tool_minimum(
        sample_run_bytes,
        "hero-1",
        minimum=10,
    )
    assert ok is True
    assert updated == 3

    obj = parse_ftk2(modified)["json"]
    things = obj["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    by_name = {entry["ConfigName"]: entry["_stackCount"] for entry in things}
    assert by_name["HERB_HEALING"] == 10
    assert by_name["TOOL_LOCKPICK"] == 10
    assert by_name["DRINK_ALE"] == 10
    assert by_name["POTION_SPEED"] == 3


def test_ensure_character_herb_tool_minimum_not_gamerun(sample_save_bytes):
    modified, ok, updated = ensure_character_herb_tool_minimum(
        sample_save_bytes,
        "hero-1",
        minimum=10,
    )
    assert modified == sample_save_bytes
    assert ok is False
    assert updated == 0


def test_ensure_character_herb_tool_minimum_tops_up_scrolls(sample_run_bytes):
    # Extend the shared run fixture with scroll + safetystone stacks below the minimum.
    run = parse_ftk2(sample_run_bytes)["json"]
    things = run["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    things.append({"ConfigName": "SCROLL_TELEPORT_01", "Type": "ITEM", "_stackCount": 1})
    things.append({"ConfigName": "SCROLL_VISION_01", "Type": "ITEM", "_stackCount": 1})
    things.append({"ConfigName": "MISC_SAFETYSTONE_01", "Type": "ITEM", "_stackCount": 1})
    things.append({"ConfigName": "ORB_FORTUNETELLER_BASIC_00", "Type": "EQUIPMENT", "_stackCount": 1})
    things.append({"ConfigName": "CANDY_LUCK", "Type": "ITEM", "_stackCount": 1})
    things.append({"ConfigName": "MISC_INK", "Type": "ITEM", "_stackCount": 1})
    summary = {"runID": "run-123", "saveName": "Test Expedition", "difficulty": "normal"}
    text = f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n"
    with_scrolls = encrypt_ftk2_text(text)

    modified, ok, updated = ensure_character_herb_tool_minimum(
        with_scrolls,
        "hero-1",
        minimum=10,
    )
    assert ok is True
    assert updated == 9  # herb + tool + drink + 2 scrolls + safetystone + orb + candy + ink

    things = parse_ftk2(modified)["json"]["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    by_name = {entry["ConfigName"]: entry["_stackCount"] for entry in things}
    assert by_name["SCROLL_TELEPORT_01"] == 10
    assert by_name["SCROLL_VISION_01"] == 10
    assert by_name["MISC_SAFETYSTONE_01"] == 10
    assert by_name["ORB_FORTUNETELLER_BASIC_00"] == 10
    assert by_name["CANDY_LUCK"] == 10
    assert by_name["MISC_INK"] == 10


def test_ensure_party_herb_tool_minimum_tops_up_everyone():
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Hero",
                        "ConfigName": "HUNTER",
                        "Things": [
                            {"ConfigName": "HERB_HEALING", "Type": "ITEM", "_stackCount": 2},
                        ],
                    },
                    "PlayerComponent": {"IsPlayer": True},
                },
            },
            {
                "Guid": "hero-2",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Sidekick",
                        "ConfigName": "BLACKSMITH",
                        "Things": [
                            {"ConfigName": "TOOL_LOCKPICK", "Type": "ITEM", "_stackCount": 1},
                            {"ConfigName": "ORB_LIGHTNING_LIGHT_00", "Type": "EQUIPMENT", "_stackCount": 1},
                        ],
                    },
                    "PlayerComponent": {"IsPlayer": True},
                },
            },
            {
                "Guid": "merc-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Merc",
                        "ConfigName": "MERC_GUN_BASIC_04",
                        "CharacterType": "MERCENARY",
                        "Things": [
                            {"ConfigName": "HERB_HEALING", "Type": "ITEM", "_stackCount": 1},
                        ],
                    },
                },
            },
        ]
    }
    summary = {"runID": "run-123", "saveName": "Test Expedition", "difficulty": "normal"}
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n")

    # Library helper is guid-list driven, so passing only the two player guids
    # naturally skips the mercenary.  That mirrors the GUI filter.
    modified, ok, updated = ensure_party_herb_tool_minimum(
        blob, ["hero-1", "hero-2"], minimum=10
    )
    assert ok is True
    assert updated == 3

    parsed = parse_ftk2(modified)["json"]
    things1 = parsed["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    things2 = parsed["Entities"][1]["Components"]["CharacterComponent"]["Things"]
    merc_things = parsed["Entities"][2]["Components"]["CharacterComponent"]["Things"]
    assert things1[0]["_stackCount"] == 10
    assert things2[0]["_stackCount"] == 10
    assert things2[1]["_stackCount"] == 10
    assert merc_things[0]["_stackCount"] == 1  # not touched


def test_replace_character_thing_swaps_config_name():
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Hero",
                        "ConfigName": "HUNTER",
                        "Things": [
                            {
                                "Id": "bow-1",
                                "ConfigName": "BOW_MILITIA_MEDIUM_00",
                                "Type": "EQUIPMENT",
                                "_stackCount": 1,
                                "Expansion": "BASE",
                            },
                        ],
                    }
                },
            }
        ]
    }
    summary = {"runID": "run-123", "saveName": "Test Expedition", "difficulty": "normal"}
    text = f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n"
    blob = encrypt_ftk2_text(text)

    modified, ok = replace_character_thing(blob, "hero-1", "bow-1", "BOW_LONGBOW_02")
    assert ok is True
    things = parse_ftk2(modified)["json"]["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    assert things[0]["ConfigName"] == "BOW_LONGBOW_02"
    assert things[0]["Id"] == "bow-1"  # equipped-slot wiring stays intact
    assert things[0]["Type"] == "EQUIPMENT"
    assert things[0]["_stackCount"] == 1


def test_add_character_thing_appends_independent_inventory_item():
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "Things": [
                            {
                                "Id": "bow-1",
                                "ConfigName": "BOW_MILITIA_MEDIUM_00",
                                "Type": "EQUIPMENT",
                                "_stackCount": 1,
                                "Expansion": "BASE",
                            }
                        ]
                    }
                },
            }
        ]
    }
    summary = {"runID": "run-123", "saveName": "Test Expedition"}
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")

    modified, ok = editor.add_character_thing(
        blob, "hero-1", "BOW_FIRE_MEDIUM_01", "EQUIPMENT", "LORE_STORE"
    )

    assert ok is True
    things = parse_ftk2(modified)["json"]["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    assert len(things) == 2
    assert things[0]["Id"] == "bow-1"
    assert things[1]["Id"] != "bow-1"
    assert things[1]["ConfigName"] == "BOW_FIRE_MEDIUM_01"
    assert things[1]["Type"] == "EQUIPMENT"
    assert things[1]["_stackCount"] == 1
    assert things[1]["Expansion"] == "LORE_STORE"


def test_replace_character_thing_missing_thing(sample_run_bytes):
    modified, ok = replace_character_thing(sample_run_bytes, "hero-1", "nope", "BOW_X")
    assert ok is False
    assert modified == sample_run_bytes


def test_replace_character_thing_not_gamerun(sample_save_bytes):
    modified, ok = replace_character_thing(sample_save_bytes, "hero-1", "bow-1", "BOW_X")
    assert ok is False
    assert modified == sample_save_bytes


@pytest.mark.parametrize("body", [[], None, "not-an-object"])
def test_item_mutations_reject_non_object_run_json(body):
    summary = {"runID": "run-123", "saveName": "Malformed Expedition"}
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(body)}\n")

    replaced, replace_ok = replace_character_thing(
        blob, "hero-1", "bow-1", "BOW_LONGBOW_02"
    )
    added, add_ok = editor.add_character_thing(
        blob, "hero-1", "BOW_FIRE_MEDIUM_01", "EQUIPMENT"
    )

    assert replace_ok is False
    assert replaced == blob
    assert add_ok is False
    assert added == blob


def test_replace_character_thing_rejects_duplicate_character_guids():
    """Fail-closed when Entities contains duplicate character GUIDs."""
    run = {
        "Entities": [
            _char_entity("hero-1", "HUNTER", [{"ConfigName": "BOW_X", "Type": "EQUIPMENT", "_stackCount": 1, "Id": "bow-1"}]),
            _char_entity("hero-1", "MAGE", [{"ConfigName": "STAFF_Y", "Type": "EQUIPMENT", "_stackCount": 1, "Id": "staff-1"}]),
        ]
    }
    summary = {"runID": "run-123", "saveName": "Test"}
    blob = _run_blob(run, summary)
    modified, ok = replace_character_thing(blob, "hero-1", "bow-1", "BOW_Z")
    assert ok is False
    assert modified == blob


def test_replace_character_thing_rejects_duplicate_thing_ids():
    """Fail-closed when Things contains duplicate Thing IDs for the target character."""
    run = {
        "Entities": [
            _char_entity("hero-1", "HUNTER", [
                {"ConfigName": "BOW_X", "Type": "EQUIPMENT", "_stackCount": 1, "Id": "bow-1"},
                {"ConfigName": "BOW_Y", "Type": "EQUIPMENT", "_stackCount": 1, "Id": "bow-1"},
            ]),
        ]
    }
    summary = {"runID": "run-123", "saveName": "Test"}
    blob = _run_blob(run, summary)
    modified, ok = replace_character_thing(blob, "hero-1", "bow-1", "BOW_Z")
    assert ok is False
    assert modified == blob


def test_add_character_thing_rejects_duplicate_character_guids():
    """Fail-closed when Entities contains duplicate character GUIDs."""
    run = {
        "Entities": [
            _char_entity("hero-1", "HUNTER", [{"ConfigName": "BOW_X", "Type": "EQUIPMENT", "_stackCount": 1, "Id": "bow-1"}]),
            _char_entity("hero-1", "MAGE", [{"ConfigName": "STAFF_Y", "Type": "EQUIPMENT", "_stackCount": 1, "Id": "staff-1"}]),
        ]
    }
    summary = {"runID": "run-123", "saveName": "Test"}
    blob = _run_blob(run, summary)
    modified, ok = editor.add_character_thing(blob, "hero-1", "BOW_FIRE_MEDIUM_01", "EQUIPMENT")
    assert ok is False
    assert modified == blob


def _run_blob(run: dict, summary: dict) -> bytes:
    text = f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n"
    return encrypt_ftk2_text(text)


def _char_entity(guid: str, config: str, things: list, *, companion: bool = False) -> dict:
    comps = {"CharacterComponent": {"DisplayName": config, "ConfigName": config, "Things": things}}
    if companion:
        comps["CharacterComponent"]["CharacterType"] = "COMPANION"
        comps["CharacterComponent"]["ExtraLives"] = 0
    else:
        comps["PlayerComponent"] = {"IsPlayer": True}
    return {"Guid": guid, "Components": comps}


@pytest.fixture
def source_run_bytes():
    return _run_blob(
        {
            "Entities": [
                _char_entity(
                    "src-hunter",
                    "HUNTER",
                    [
                        {"ConfigName": "HERB_HEALING", "Type": "ITEM", "_stackCount": 5},
                        {"ConfigName": "TOOL_LOCKPICK", "Type": "ITEM", "_stackCount": 3},
                        {
                            "ConfigName": "SCROLL_TELEPORT_01",
                            "Type": "SPECIAL",
                            "_stackCount": 2,
                            "Expansion": "LORE_STORE",
                        },
                    ],
                ),
                _char_entity(
                    "src-blacksmith",
                    "BLACKSMITH",
                    [
                        {"ConfigName": "MISC_SAFETYSTONE_01", "Type": "ITEM", "_stackCount": 4},
                        {"ConfigName": "WEAPON_SWORD", "Type": "EQUIPMENT", "_stackCount": 1},
                        {"ConfigName": "CURRENCY_ADVENTURE", "_stackCount": 999},
                        {"ConfigName": "XP", "Type": "PASSIVE", "_stackCount": 12345},
                    ],
                ),
                _char_entity("src-pet", "SPIDER", [], companion=True),
            ],
        },
        {"runID": "source-run", "saveName": "Previous Act", "difficulty": "normal"},
    )


@pytest.fixture
def target_run_bytes():
    return _run_blob(
        {
            "Entities": [
                _char_entity(
                    "tgt-hunter",
                    "HUNTER",
                    [
                        {"ConfigName": "HERB_HEALING", "Type": "ITEM", "_stackCount": 2},
                        {"ConfigName": "MISC_SAFETYSTONE_01", "Type": "ITEM", "_stackCount": 1},
                    ],
                ),
                _char_entity(
                    "tgt-blacksmith",
                    "BLACKSMITH",
                    [
                        {"ConfigName": "TOOL_LOCKPICK", "Type": "ITEM", "_stackCount": 1},
                        {"ConfigName": "CURRENCY_ADVENTURE", "_stackCount": 50},
                        {"ConfigName": "XP", "Type": "PASSIVE", "_stackCount": 100},
                    ],
                ),
            ]
        },
        {"id": "current-run", "saveName": "Current Act", "difficulty": "normal"},
    )


def test_carry_over_consumables_roundtrip(source_run_bytes, target_run_bytes):
    modified, ok, updated = carry_over_consumables(target_run_bytes, source_run_bytes)
    assert ok is True
    assert updated == 4  # herb, tool, scroll, safetystone

    obj = parse_ftk2(modified)["json"]
    by_entity = {
        e["Guid"]: {t["ConfigName"]: t["_stackCount"] for t in e["Components"]["CharacterComponent"]["Things"]}
        for e in obj["Entities"]
    }
    # HERB + SCROLL land on the HUNTER (dominant class matches), added to existing/absent.
    assert by_entity["tgt-hunter"]["HERB_HEALING"] == 2 + 5
    assert by_entity["tgt-hunter"]["SCROLL_TELEPORT_01"] == 2
    target_hunter = next(e for e in obj["Entities"] if e["Guid"] == "tgt-hunter")
    scroll = next(
        t
        for t in target_hunter["Components"]["CharacterComponent"]["Things"]
        if t["ConfigName"] == "SCROLL_TELEPORT_01"
    )
    assert scroll["Type"] == "SPECIAL"
    assert scroll["Expansion"] == "LORE_STORE"
    # SAFETYSTONE dominant holder is BLACKSMITH in source -> a NEW safetystone entry on target BLACKSMITH.
    assert by_entity["tgt-blacksmith"]["MISC_SAFETYSTONE_01"] == 4
    # Target HUNTER's own pre-existing safetystone is untouched.
    assert by_entity["tgt-hunter"]["MISC_SAFETYSTONE_01"] == 1
    # TOOL_LOCKPICK dominant holder is HUNTER (3 vs 0 elsewhere) -> goes to HUNTER.
    assert by_entity["tgt-hunter"]["TOOL_LOCKPICK"] == 3
    # Equipment, gold, XP never copied (target keeps its own gold/XP as-is).
    all_configs = {
        t["ConfigName"]
        for e in obj["Entities"]
        for t in e["Components"]["CharacterComponent"]["Things"]
    }
    assert "WEAPON_SWORD" not in all_configs
    assert by_entity["tgt-blacksmith"]["CURRENCY_ADVENTURE"] == 50
    assert by_entity["tgt-blacksmith"]["XP"] == 100


def test_carry_over_consumables_excludes_eq_gold_xp(source_run_bytes, target_run_bytes):
    # Source's BLACKSMITH holds equipment, gold, and XP that must not be copied.
    modified, ok, updated = carry_over_consumables(target_run_bytes, source_run_bytes)
    assert ok is True
    obj = parse_ftk2(modified)["json"]
    target_hunter = next(e for e in obj["Entities"] if e["Guid"] == "tgt-hunter")
    target_smith = next(e for e in obj["Entities"] if e["Guid"] == "tgt-blacksmith")
    extra_smith = target_smith["Components"]["CharacterComponent"]["Things"]
    configs_smith = {t["ConfigName"] for t in extra_smith}
    assert "WEAPON_SWORD" not in configs_smith
    hunter_configs = {t["ConfigName"] for t in target_hunter["Components"]["CharacterComponent"]["Things"]}
    assert "XP" not in hunter_configs
    # gold stack untouched (still at its current 50)
    gold = next(t for t in extra_smith if t["ConfigName"] == "CURRENCY_ADVENTURE")
    assert gold["_stackCount"] == 50


def test_carry_over_non_gamerun_returns_unchanged(sample_save_bytes, source_run_bytes):
    modified, ok, updated = carry_over_consumables(sample_save_bytes, source_run_bytes)
    assert ok is False
    assert updated == 0
    assert modified == sample_save_bytes


def test_carry_over_empty_source_noop(target_run_bytes):
    # Source has no consumables to carry (only equipment/gold/XP) -> no-op.
    empty = _run_blob(
        {
            "Entities": [
                _char_entity(
                    "a",
                    "HUNTER",
                    [
                        {"ConfigName": "WEAPON_SWORD", "Type": "EQUIPMENT", "_stackCount": 1},
                        {"ConfigName": "CURRENCY_ADVENTURE", "_stackCount": 999},
                    ],
                )
            ]
        },
        {"id": "empty-run", "saveName": "Empty", "difficulty": "normal"},
    )
    modified, ok, updated = carry_over_consumables(target_run_bytes, empty)
    assert ok is True
    assert updated == 0
    assert modified == target_run_bytes


@pytest.mark.parametrize("invalid_body", [[], None, "not-an-object"])
def test_carry_over_rejects_non_object_run_json(target_run_bytes, source_run_bytes, invalid_body):
    malformed = _run_blob(
        invalid_body,
        {"id": "malformed-run", "saveName": "Malformed", "difficulty": "normal"},
    )

    modified, ok, updated = carry_over_consumables(malformed, source_run_bytes)
    assert (modified, ok, updated) == (malformed, False, 0)

    modified, ok, updated = carry_over_consumables(target_run_bytes, malformed)
    assert (modified, ok, updated) == (target_run_bytes, False, 0)


def test_carry_over_empty_source_rejects_invalid_target(target_run_bytes):
    """Valid source with no consumables must still reject a target with no party."""
    empty_source = _run_blob(
        {
            "Entities": [
                _char_entity(
                    "a",
                    "HUNTER",
                    [
                        {"ConfigName": "WEAPON_SWORD", "Type": "EQUIPMENT", "_stackCount": 1},
                        {"ConfigName": "CURRENCY_ADVENTURE", "_stackCount": 999},
                    ],
                )
            ]
        },
        {"id": "empty-source", "saveName": "Empty", "difficulty": "normal"},
    )
    # Target with empty Entities -> no party
    invalid_target = _run_blob(
        {"Entities": []},
        {"id": "invalid-target", "saveName": "Invalid", "difficulty": "normal"},
    )
    modified, ok, updated = carry_over_consumables(invalid_target, empty_source)
    assert (modified, ok, updated) == (invalid_target, False, 0)


def test_ensure_character_herb_tool_minimum_tops_up_thrown(sample_run_bytes):
    # THROW_ configs (Type=EQUIPMENT) must now be topped up to the minimum too.
    run = parse_ftk2(sample_run_bytes)["json"]
    things = run["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    things.append({"ConfigName": "THROW_MILITIA_BOMB_00", "Type": "EQUIPMENT", "_stackCount": 1})
    things.append({"ConfigName": "THROW_MILITIA_FIRE_00", "Type": "EQUIPMENT", "_stackCount": 1})
    summary = {"runID": "run-123", "saveName": "Test Expedition", "difficulty": "normal"}
    text = f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n"
    with_thrown = encrypt_ftk2_text(text)

    modified, ok, updated = ensure_character_herb_tool_minimum(
        with_thrown,
        "hero-1",
        minimum=10,
    )
    assert ok is True
    assert updated == 5  # herb + tool + drink + 2 thrown stacks

    things = parse_ftk2(modified)["json"]["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    by_name = {entry["ConfigName"]: entry["_stackCount"] for entry in things}
    assert by_name["THROW_MILITIA_BOMB_00"] == 10
    assert by_name["THROW_MILITIA_FIRE_00"] == 10


def test_verify_save_roundtrip(sample_user_obj, tmp_path):
    # Hermetic: verify a save written to disk by our own tooling parses back
    # cleanly, without depending on a local game install.
    save_path = tmp_path / "User.ftk2"
    text = json.dumps(sample_user_obj, indent=2) + "\n"
    save_path.write_bytes(encrypt_ftk2_text(text))
    data = save_path.read_bytes()
    result = verify_save(data)
    assert result["file_size"] > 0
    assert result["has_bom"] is True
    assert result["decrypts_to_json"] is True
    assert result["valid"] is True
    parsed = parse_ftk2(data)
    assert isinstance(parsed["json"], dict)
    assert "LocalStats" in parsed["json"]


def _run_blob_with_names(entities: list[dict]) -> bytes:
    summary = {"runID": "run-rename", "saveName": "Rename Test", "difficulty": "normal"}
    run = {"Entities": entities}
    text = f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n"
    return encrypt_ftk2_text(text)


@pytest.fixture
def rename_run_blob() -> bytes:
    return _run_blob_with_names(
        [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Hero",
                        "ConfigName": "HUNTER",
                        "Things": [{"ConfigName": "HERB_HEALING", "Type": "ITEM", "_stackCount": 2}],
                    }
                },
            },
            {
                "Guid": "hero-2",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Sidekick",
                        "ConfigName": "BLACKSMITH",
                        "Things": [],
                    }
                },
            },
        ]
    )


def test_rename_party_member_by_guid(rename_run_blob):
    modified, ok = rename_party_member(rename_run_blob, "Sir Hero", guid="hero-1")
    assert ok is True
    parsed = parse_ftk2(modified)
    assert parsed["summary"]["runID"] == "run-rename"
    entity = parsed["json"]["Entities"][0]
    assert entity["Components"]["CharacterComponent"]["DisplayName"] == "Sir Hero"
    assert entity["Components"]["CharacterComponent"]["ConfigName"] == "HUNTER"
    assert entity["Components"]["CharacterComponent"]["Things"][0]["_stackCount"] == 2


def test_rename_party_member_by_current_name(rename_run_blob):
    modified, ok = rename_party_member(rename_run_blob, "Archer", current_name="Hero")
    assert ok is True
    parsed = parse_ftk2(modified)["json"]
    names = [
        e["Components"]["CharacterComponent"]["DisplayName"]
        for e in parsed["Entities"]
    ]
    assert names == ["Archer", "Sidekick"]


def test_rename_party_member_unknown_guid_fails(rename_run_blob):
    modified, ok = rename_party_member(rename_run_blob, "Nobody", guid="missing")
    assert ok is False
    assert modified is rename_run_blob  # unchanged


def test_rename_party_member_blank_name_fails(rename_run_blob):
    modified, ok = rename_party_member(rename_run_blob, "   ", guid="hero-1")
    assert ok is False
    assert modified is rename_run_blob


def test_rename_party_member_ambiguous_current_name_fails():
    blob = _run_blob_with_names(
        [
            {
                "Guid": "hero-1",
                "Components": {"CharacterComponent": {"DisplayName": "Hero", "ConfigName": "HUNTER", "Things": []}},
            },
            {
                "Guid": "hero-2",
                "Components": {"CharacterComponent": {"DisplayName": "Hero", "ConfigName": "WARRIOR", "Things": []}},
            },
        ]
    )
    modified, ok = rename_party_member(blob, "Winner", current_name="Hero")
    assert ok is False  # ambiguous -> fail closed
    assert modified is blob


def test_rename_party_member_noncharacter_guid_fails():
    blob = _run_blob_with_names([{"Guid": "npc-1", "Components": {"NpcComponent": {}}}])
    modified, ok = rename_party_member(blob, "NoName", guid="npc-1")
    assert ok is False
    assert modified is blob


def test_rename_party_member_user_save():
    user = {
        "PartyCharacters": [
            {
                "Guid": "c-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "Old", "ConfigName": "HUNTER", "Things": []}
                },
            }
        ],
        "LocalStats": {"LANG_ID": 1},
    }
    blob = encrypt_ftk2_text(json.dumps(user, indent=2) + "\n")
    modified, ok = rename_party_member(blob, "New", current_name="Old")
    assert ok is True
    parsed = parse_ftk2(modified)["json"]
    cc = parsed["PartyCharacters"][0]["Components"]["CharacterComponent"]
    assert cc["DisplayName"] == "New"
    assert parsed["LocalStats"]["LANG_ID"] == 1


def test_rename_party_member_no_entities_fails(sample_user_obj):
    blob = encrypt_ftk2_text(json.dumps(sample_user_obj, indent=2) + "\n")
    modified, ok = rename_party_member(blob, "Anyone", guid="nope")
    assert ok is False
    assert modified is blob


@pytest.fixture
def user_roster_blob() -> bytes:
    user = {
        "PartyCharacters": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "Hero", "ConfigName": "HUNTER", "Things": []}
                },
            },
            {
                "Guid": "hero-2",
                "Components": {
                    "CharacterComponent": {"DisplayName": "Sidekick", "ConfigName": "BLACKSMITH", "Things": []}
                },
            },
        ],
        "LastRunCharacters": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "Hero", "ConfigName": "HUNTER", "Things": []}
                },
            },
        ],
        "LocalStats": {"LANG_ID": 1},
    }
    return encrypt_ftk2_text(dump_user_json(user))


def test_rename_party_member_synced_updates_user_roster(
    rename_run_blob, user_roster_blob
):
    modified, ok, user_modified = rename_party_member_synced(
        rename_run_blob, "Sir Hero", guid="hero-1", user_data=user_roster_blob
    )
    assert ok is True
    assert user_modified is not None
    parsed = parse_ftk2(modified)["json"]
    assert parsed["Entities"][0]["Components"]["CharacterComponent"]["DisplayName"] == "Sir Hero"

    user = parse_ftk2(user_modified)["json"]
    pc = user["PartyCharacters"]
    assert pc[0]["Components"]["CharacterComponent"]["DisplayName"] == "Sir Hero"
    assert pc[1]["Components"]["CharacterComponent"]["DisplayName"] == "Sidekick"  # untouched
    assert user["LastRunCharacters"][0]["Components"]["CharacterComponent"]["DisplayName"] == "Sir Hero"
    assert user["LocalStats"]["LANG_ID"] == 1


def test_rename_party_member_synced_by_current_name(rename_run_blob, user_roster_blob):
    modified, ok, user_modified = rename_party_member_synced(
        rename_run_blob, "Archer", current_name="Hero", user_data=user_roster_blob
    )
    assert ok is True
    assert user_modified is not None
    user = parse_ftk2(user_modified)["json"]
    assert user["PartyCharacters"][0]["Components"]["CharacterComponent"]["DisplayName"] == "Archer"
    assert user["LastRunCharacters"][0]["Components"]["CharacterComponent"]["DisplayName"] == "Archer"


def test_rename_party_member_synced_no_user_data(rename_run_blob):
    modified, ok, user_modified = rename_party_member_synced(
        rename_run_blob, "Sir Hero", guid="hero-1", user_data=None
    )
    assert ok is True
    assert user_modified is None


def test_rename_party_member_synced_roster_guids_dont_match(rename_run_blob, user_roster_blob):
    # User roster only holds hero-1/hero-2, not "other"; nothing synced but run rename succeeds.
    modified, ok, user_modified = rename_party_member_synced(
        rename_run_blob, "Sir Hero", guid="other", user_data=user_roster_blob
    )
    assert ok is False  # run rename itself failed -> untouched
    assert modified is rename_run_blob


def test_rename_party_member_synced_bad_user_data(rename_run_blob):
    bad_user = encrypt_ftk2_text("not json at all")
    modified, ok, user_modified = rename_party_member_synced(
        rename_run_blob, "Sir Hero", guid="hero-1", user_data=bad_user
    )
    assert ok is True
    assert user_modified is None  # run rename still succeeded, roster skipped
    parsed = parse_ftk2(modified)["json"]
    assert parsed["Entities"][0]["Components"]["CharacterComponent"]["DisplayName"] == "Sir Hero"


def test_rename_party_member_corrupt_bytes_fails():
    # Undecodable payload must fail-closed, not propagate a UnicodeDecodeError.
    corrupt = b"\xff\xfe not utf8 \x80\x81"
    modified, ok = rename_party_member(corrupt, "X", guid="hero-1")
    assert ok is False
    assert modified is corrupt


def test_rename_party_member_synced_corrupt_user_fails_closed(rename_run_blob):
    # A cryptographically valid run but garbage User bytes: run rename still
    # succeeds, roster is skipped (None), nothing raises.
    bad_user = b"\xff\xfe\x80\x81"
    modified, ok, user_modified = rename_party_member_synced(
        rename_run_blob, "Sir Hero", guid="hero-1", user_data=bad_user
    )
    assert ok is True
    assert user_modified is None
    parsed = parse_ftk2(modified)["json"]
    assert parsed["Entities"][0]["Components"]["CharacterComponent"]["DisplayName"] == "Sir Hero"


def test_rename_party_member_synced_failure_returns_none(rename_run_blob, user_roster_blob):
    # Failed run rename must return (data, False, None) -- never the caller's
    # original user bytes, which would look like a successful sync.
    modified, ok, user_modified = rename_party_member_synced(
        rename_run_blob, "Nobody", guid="nope", user_data=user_roster_blob
    )
    assert ok is False
    assert modified is rename_run_blob
    assert user_modified is None


def _run_blob_with_tickets() -> bytes:
    summary = {"runID": "run-tix", "saveName": "Carnival", "difficulty": "normal"}
    run = {
        "Entities": [],
        "DungeonState": {
            "ChoiceStack": [
                None,
                {
                    "ID": "DARK_CARNIVAL_NECROMANCER",
                    "KeyItem": "MISC_CARNIVALTICKET_01",
                    "KeyAmount": 6,
                    "DisplayName": "DUNGEON_BRANCH_NECROMANCER",
                },
            ]
        },
        "ItemPools": {"CURRENCY_LORE": 0, "MISC_CARNIVALTICKET_01": 4},
    }
    text = f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n"
    return encrypt_ftk2_text(text)


def test_set_carnival_tickets_sets_50():
    modified, ok = set_carnival_tickets(_run_blob_with_tickets(), 50)
    assert ok is True
    obj = parse_ftk2(modified)["json"]
    assert obj["ItemPools"]["MISC_CARNIVALTICKET_01"] == 50
    assert obj["ItemPools"]["CURRENCY_LORE"] == 0  # untouched
    assert obj["DungeonState"]["ChoiceStack"][1]["KeyAmount"] == 6  # untouched


def test_set_carnival_tickets_negative_raises():
    with pytest.raises(ValueError):
        set_carnival_tickets(_run_blob_with_tickets(), -1)


def test_set_carnival_tickets_rejects_float_and_bool():
    with pytest.raises(ValueError):
        set_carnival_tickets(_run_blob_with_tickets(), 6.9)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        set_carnival_tickets(_run_blob_with_tickets(), True)


def test_set_carnival_tickets_non_mapping_body_fails():
    summary = {"runID": "r", "saveName": "s", "difficulty": "normal"}
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n[]\n")
    modified, ok = set_carnival_tickets(blob, 50)
    assert ok is False
    assert modified is blob


def test_set_carnival_tickets_adds_missing_key():
    summary = {"runID": "r", "saveName": "s", "difficulty": "normal"}
    run = {"Entities": [], "ItemPools": {"CURRENCY_LORE": 5}}
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok = set_carnival_tickets(blob, 50)
    assert ok is True
    obj = parse_ftk2(modified)["json"]
    assert obj["ItemPools"]["MISC_CARNIVALTICKET_01"] == 50
    assert obj["ItemPools"]["CURRENCY_LORE"] == 5


def test_set_carnival_tickets_no_itempools_fails(sample_run_bytes):
    modified, ok = set_carnival_tickets(sample_run_bytes, 50)
    assert ok is False
    assert modified is sample_run_bytes


def test_set_carnival_tickets_not_gamerun_fails(sample_user_obj):
    blob = encrypt_ftk2_text(json.dumps(sample_user_obj, indent=2) + "\n")
    modified, ok = set_carnival_tickets(blob, 50)
    assert ok is False
    assert modified is blob


def test_give_carnival_wheel_piece_adds_to_character(sample_run_bytes):
    modified, ok = give_carnival_wheel_piece(sample_run_bytes, "hero-1")
    assert ok is True
    run = parse_ftk2(modified)["json"]
    things = run["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    piece = [t for t in things if t.get("ConfigName") == "MISC_WHEELPIECE_01"]
    assert len(piece) == 1
    assert piece[0]["Type"] == "ITEM"
    assert piece[0]["_stackCount"] == 1
    assert piece[0]["CustomData"] == {"ID": "PLAYERS_FULL_HEAL"}
    assert piece[0]["Expansion"] == "BASE"
    assert sum(1 for t in things if t.get("ConfigName") == "HERB_HEALING") == 1


def test_give_carnival_wheel_piece_keeps_other_characters(sample_run_bytes):
    run = parse_ftk2(sample_run_bytes)["json"]
    run["Entities"] = [
        {"Guid": "hero-1", "Components": {"CharacterComponent": {"DisplayName": "A", "ConfigName": "HUNTER", "Things": []}}},
        {"Guid": "hero-2", "Components": {"CharacterComponent": {"DisplayName": "B", "ConfigName": "MONK", "Things": []}}},
    ]
    summary = {"runID": "r", "saveName": "s", "difficulty": "normal"}
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok = give_carnival_wheel_piece(blob, "hero-2")
    assert ok is True
    run2 = parse_ftk2(modified)["json"]
    a = run2["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    b = run2["Entities"][1]["Components"]["CharacterComponent"]["Things"]
    assert a == []
    assert [t["ConfigName"] for t in b] == ["MISC_WHEELPIECE_01"]


def test_give_carnival_wheel_piece_already_has_fails(sample_run_bytes):
    modified, ok = give_carnival_wheel_piece(sample_run_bytes, "hero-1")
    assert ok is True
    again, ok2 = give_carnival_wheel_piece(modified, "hero-1")
    assert ok2 is False
    assert again is modified


def test_give_carnival_wheel_piece_bad_character_fails(sample_run_bytes):
    modified, ok = give_carnival_wheel_piece(sample_run_bytes, "nope")
    assert ok is False
    assert modified is sample_run_bytes


def test_give_carnival_wheel_piece_not_gamerun_fails(sample_user_obj):
    blob = encrypt_ftk2_text(json.dumps(sample_user_obj, indent=2) + "\n")
    modified, ok = give_carnival_wheel_piece(blob, "hero-1")
    assert ok is False
    assert modified is blob


def _snack_run_blob() -> bytes:
    summary = {"runID": "snack", "saveName": "S", "difficulty": "normal"}
    run = {
        "Entities": [
            {"Guid": "hero-1", "Components": {"CharacterComponent": {"DisplayName": "A", "ConfigName": "HUNTER", "Things": [
                {"ConfigName": "SNICKERDOODLE_BASIC_01", "Type": "ITEM", "_stackCount": 3},
                {"ConfigName": "HOTDOG_BASIC_01", "Type": "ITEM", "_stackCount": 1},
            ]}}},
            {"Guid": "hero-2", "Components": {"CharacterComponent": {"DisplayName": "B", "ConfigName": "MONK", "Things": [
                {"ConfigName": "SNICKERDOODLE_BASIC_01", "Type": "ITEM", "_stackCount": 7},
                {"ConfigName": "HERB_HEALING", "Type": "ITEM", "_stackCount": 4},
            ]}}},
        ]
    }
    return encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")


def test_ensure_party_food_minimum_tops_up_snacks():
    modified, ok, updated = ensure_party_food_minimum(
        _snack_run_blob(), ["hero-1", "hero-2"], minimum=10
    )
    assert ok is True
    assert updated == 3  # two snacks + one snack
    run = parse_ftk2(modified)["json"]
    a = {t["ConfigName"]: t["_stackCount"] for t in run["Entities"][0]["Components"]["CharacterComponent"]["Things"]}
    b = {t["ConfigName"]: t["_stackCount"] for t in run["Entities"][1]["Components"]["CharacterComponent"]["Things"]}
    assert a["SNICKERDOODLE_BASIC_01"] == 10
    assert a["HOTDOG_BASIC_01"] == 10
    assert b["SNICKERDOODLE_BASIC_01"] == 10
    assert b["HERB_HEALING"] == 4  # not a snack, untouched


def test_ensure_party_food_minimum_leaves_already_high():
    blob = _snack_run_blob()
    modified, ok, updated = ensure_party_food_minimum(
        blob, ["hero-1", "hero-2"], minimum=10
    )
    again, ok2, updated2 = ensure_party_food_minimum(
        modified, ["hero-1", "hero-2"], minimum=10
    )
    assert ok2 is True
    assert updated2 == 0
    assert again is modified


def test_ensure_party_food_minimum_empty_guids():
    blob = _snack_run_blob()
    modified, ok, updated = ensure_party_food_minimum(blob, [], minimum=10)
    assert ok is False
    assert updated == 0
    assert modified is blob


def test_ensure_party_food_minimum_not_gamerun_fails(sample_user_obj):
    blob = encrypt_ftk2_text(json.dumps(sample_user_obj, indent=2) + "\n")
    modified, ok, updated = ensure_party_food_minimum(blob, ["hero-1"], minimum=10)
    assert ok is False
    assert updated == 0
    assert modified is blob


def test_ensure_party_food_minimum_non_mapping_body_fails():
    summary = {"runID": "r", "saveName": "s", "difficulty": "normal"}
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n[]\n")
    modified, ok, updated = ensure_party_food_minimum(blob, ["hero-1"], minimum=10)
    assert ok is False
    assert updated == 0
    assert modified is blob


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
