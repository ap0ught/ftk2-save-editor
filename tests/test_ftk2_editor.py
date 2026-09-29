"""Tests for the FTK2 save editor (XOR-encrypted JSON)."""

from __future__ import annotations

import json

import pytest
import ftk2_editor as editor

from ftk2_editor import (
    ENCRYPT_KEY,
    add_evil_reflection,
    add_mercenary,
    add_pet,
    add_character_thing_stack,
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
    remove_follower,
    repair_follower_placement,
    rename_party_member,
    rename_party_member_synced,
    replace_character_thing,
    give_carnival_wheel_piece,
    grant_thing_to_party,
    set_carnival_tickets,
    set_character_thing_stack,
    swap_character_class,
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


def _topup_run_blob(things_by_guid):
    entities = [
        {"Guid": guid, "Components": {"CharacterComponent": {"Things": things}}}
        for guid, things in things_by_guid.items()
    ]
    summary = {"runID": "run-123", "saveName": "Test Expedition", "difficulty": "normal"}
    run = {"Entities": entities}
    return encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n")


def _things_by_config(blob, guid):
    for entity in parse_ftk2(blob)["json"]["Entities"]:
        if entity["Guid"] == guid:
            things = entity["Components"]["CharacterComponent"]["Things"]
            return {thing["ConfigName"]: thing["_stackCount"] for thing in things}
    raise AssertionError(f"guid {guid} not found")


def test_herb_minimum_raises_herbs_but_not_other_consumables():
    blob = _topup_run_blob(
        {
            "hero-1": [
                {"ConfigName": "HERB_HEALING", "Type": "ITEM", "_stackCount": 2},
                {"ConfigName": "TOOL_LOCKPICK", "Type": "ITEM", "_stackCount": 1},
            ]
        }
    )
    modified, ok, updated = ensure_character_herb_tool_minimum(
        blob, "hero-1", minimum=10, herb_minimum=15
    )
    assert ok is True
    assert updated == 2
    by_name = _things_by_config(modified, "hero-1")
    assert by_name["HERB_HEALING"] == 15
    assert by_name["TOOL_LOCKPICK"] == 10


def test_godsbeard_reaches_50_only_for_healers():
    blob = _topup_run_blob(
        {
            "healer": [{"ConfigName": "HERB_GODSBEARD_01", "Type": "ITEM", "_stackCount": 1}],
            "fighter": [{"ConfigName": "HERB_GODSBEARD_01", "Type": "ITEM", "_stackCount": 1}],
        }
    )
    modified, ok, updated = ensure_party_herb_tool_minimum(
        blob,
        ["healer", "fighter"],
        minimum=10,
        herb_minimum=15,
        godsbeard_minimum=50,
        healers={"healer"},
    )
    assert ok is True
    assert updated == 2
    assert _things_by_config(modified, "healer")["HERB_GODSBEARD_01"] == 50
    assert _things_by_config(modified, "fighter")["HERB_GODSBEARD_01"] == 15


def test_kibble_reaches_50_only_for_pet_owners():
    blob = _topup_run_blob(
        {
            "owner": [{"ConfigName": "TOOL_KIBBLE_01", "Type": "ITEM", "_stackCount": 3}],
            "solo": [{"ConfigName": "TOOL_KIBBLE_01", "Type": "ITEM", "_stackCount": 3}],
        }
    )
    modified, ok, updated = ensure_party_herb_tool_minimum(
        blob,
        ["owner", "solo"],
        minimum=10,
        kibble_minimum=50,
        pet_owners={"owner"},
    )
    assert ok is True
    assert updated == 1
    assert _things_by_config(modified, "owner")["TOOL_KIBBLE_01"] == 50
    # No pet: kibble is deliberately left alone (not even raised to the generic 10).
    assert _things_by_config(modified, "solo")["TOOL_KIBBLE_01"] == 3


def test_kibble_falls_back_to_generic_minimum_without_policy():
    blob = _topup_run_blob(
        {"solo": [{"ConfigName": "TOOL_KIBBLE_01", "Type": "ITEM", "_stackCount": 3}]}
    )
    modified, ok, updated = ensure_party_herb_tool_minimum(blob, ["solo"], minimum=10)
    assert ok is True
    assert updated == 1
    assert _things_by_config(modified, "solo")["TOOL_KIBBLE_01"] == 10


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


def _mirror_stacks(blob: bytes, guid: str) -> list[dict]:
    run = parse_ftk2(blob)["json"]
    for entity in run["Entities"]:
        if entity["Guid"] == guid:
            return [
                t
                for t in entity["Components"]["CharacterComponent"]["Things"]
                if t.get("ConfigName") == "MISC_MIRROR_01"
            ]
    raise AssertionError(f"{guid} not found")


def test_add_character_thing_stack_appends_when_absent():
    blob = _run_blob(
        {"Entities": [_char_entity("hero-1", "HUNTER", [{"ConfigName": "HERB_HEALING", "Type": "ITEM", "_stackCount": 5}])]},
        {"runID": "run-123", "saveName": "Test"},
    )
    modified, ok, total = add_character_thing_stack(blob, "hero-1", "MISC_MIRROR_01", 10)
    assert ok is True
    assert total == 10
    stacks = _mirror_stacks(modified, "hero-1")
    assert len(stacks) == 1, "a missing item must not be added as ten separate entries"
    assert stacks[0]["_stackCount"] == 10
    assert stacks[0]["Type"] == "ITEM"
    assert stacks[0]["Id"], "a new stack needs an Id"


def test_add_character_thing_stack_merges_into_an_existing_stack():
    blob = _run_blob(
        {
            "Entities": [
                _char_entity(
                    "hero-1",
                    "HUNTER",
                    [
                        {
                            "ConfigName": "MISC_MIRROR_01",
                            "Type": "ITEM",
                            "_stackCount": 1,
                            "Id": "mirror-1",
                            "Expansion": "BASE",
                        }
                    ],
                )
            ]
        },
        {"runID": "run-123", "saveName": "Test"},
    )
    modified, ok, total = add_character_thing_stack(blob, "hero-1", "MISC_MIRROR_01", 10)
    assert ok is True
    assert total == 11
    stacks = _mirror_stacks(modified, "hero-1")
    assert len(stacks) == 1
    assert stacks[0]["_stackCount"] == 11
    assert stacks[0]["Id"] == "mirror-1", "merging must keep the stack's Id"


def test_add_character_thing_stack_accumulates_across_calls():
    def fresh() -> bytes:
        return _run_blob(
            {"Entities": [_char_entity("hero-1", "HUNTER", [])]},
            {"runID": "run-123", "saveName": "Test"},
        )

    blob, ok, total = add_character_thing_stack(fresh(), "hero-1", "MISC_MIRROR_01", 10)
    assert ok and total == 10
    blob, ok, total = add_character_thing_stack(blob, "hero-1", "MISC_MIRROR_01", 10)
    assert ok and total == 20
    assert len(_mirror_stacks(blob, "hero-1")) == 1
    assert _mirror_stacks(blob, "hero-1")[0]["_stackCount"] == 20


def test_add_character_thing_stack_does_not_touch_other_types_or_expansions():
    blob = _run_blob(
        {
            "Entities": [
                _char_entity(
                    "hero-1",
                    "HUNTER",
                    [
                        {
                            "ConfigName": "MISC_MIRROR_01",
                            "Type": "EQUIPMENT",
                            "_stackCount": 1,
                            "Id": "shield-1",
                            "Expansion": "BASE",
                        }
                    ],
                )
            ]
        },
        {"runID": "run-123", "saveName": "Test"},
    )
    modified, ok, _total = add_character_thing_stack(blob, "hero-1", "MISC_MIRROR_01", 10)
    assert ok is True
    run = parse_ftk2(modified)["json"]
    things = run["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    equipment = [t for t in things if t["Type"] == "EQUIPMENT"]
    assert equipment[0]["_stackCount"] == 1, "an EQUIPMENT entry must not be stacked"
    assert len([t for t in things if t["Type"] == "ITEM"]) == 1


def test_add_character_thing_stack_fails_closed():
    blob = _run_blob(
        {"Entities": [_char_entity("hero-1", "HUNTER", [])]},
        {"runID": "run-123", "saveName": "Test"},
    )
    user_blob = encrypt_ftk2_text(json.dumps({"LocalStats": {}}, indent=2) + "\n")
    # unknown character, not a run, and non-positive counts all leave data alone
    for args in (
        (user_blob, "hero-1", "MISC_MIRROR_01", 10),
        (blob, "nobody", "MISC_MIRROR_01", 10),
        (blob, "hero-1", "", 10),
        (blob, "hero-1", "MISC_MIRROR_01", 0),
        (blob, "hero-1", "MISC_MIRROR_01", -3),
    ):
        modified, ok, total = add_character_thing_stack(*args)
        assert ok is False
        assert total == 0
        assert modified == args[0]


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


def _merc_run_blob() -> bytes:
    """A run with one player (PlayerComponent) standing in as the host."""
    summary = {"runID": "merc-run", "saveName": "M", "difficulty": "normal"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Host",
                        "ConfigName": "HUNTER",
                        "Things": [],
                    },
                    "PlayerComponent": {"IsPlayer": True},
                },
            }
        ]
    }
    return encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")


def test_add_mercenary_creates_follower_bound_to_player():
    spec = {
        "type_args": "MERC_GUN_01",
        "config_name": "MERC_GUN_BASIC_06",
        "contract_rounds": 6,
        "start_health": 120,
        "start_focus": 0,
        "start_things": ["GUN_MILITIA_TINY_03"],
    }
    modified, ok, guid = add_mercenary(_merc_run_blob(), "hero-1", spec)
    assert ok is True
    assert guid

    run = parse_ftk2(modified)["json"]
    entities = run["Entities"]
    assert len(entities) == 2
    merc = [e for e in entities if e["Guid"] == guid]
    assert len(merc) == 1
    cc = merc[0]["Components"]["CharacterComponent"]
    assert cc["ConfigName"] == "MERC_GUN_BASIC_06"
    assert cc["CharacterType"] == "MERCENARY"
    assert cc["TypeArgs"] == "MERC_GUN_01"
    assert cc["CurrentHealth"] == 120
    things = cc["Things"]
    assert len(things) == 1
    assert things[0]["ConfigName"] == "GUN_MILITIA_TINY_03"
    assert things[0]["Type"] == "EQUIPMENT"
    assert cc["Equipped"]["MAIN_HAND"] == things[0]["Id"]

    followers = run["PlayerFollowers"]
    assert isinstance(followers, dict)
    assert followers["hero-1"] == {"FollowerID": guid, "RoundsToExpire": 6}


def test_add_mercenary_keeps_host_position_components():
    summary = {"runID": "merc-run", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "H", "ConfigName": "HUNTER", "Things": []},
                    "PlayerComponent": {"IsPlayer": True},
                    "AvatarComponent": {"PrimaryColor": "AABBCC"},
                    "AdventureComponent": {"HexPosition": {"Item1": 5, "Item2": 7}, "MapID": "MAP_1"},
                    "VenueComponent": {"TilePosition": {"Item1": 1, "Item2": 2}},
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    spec = {"config_name": "MERC_A_BASIC_00", "start_things": []}
    modified, ok, guid = add_mercenary(blob, "hero-1", spec)
    assert ok is True
    run2 = parse_ftk2(modified)["json"]
    merc = [e for e in run2["Entities"] if e["Guid"] == guid][0]
    comps = merc["Components"]
    assert comps["AvatarComponent"]["PrimaryColor"] == "AABBCC"
    assert comps["AdventureComponent"]["HexPosition"] == {"Item1": 5, "Item2": 7}
    # nudged one tile along Item1 so the merc does not stack on the hero
    # nudged one tile along Item1 so the merc does not stack on the hero
    assert comps["VenueComponent"]["TilePosition"] == {"Item1": 2, "Item2": 2}
    # keys the host venue does not have are not invented
    assert "OccupiedTiles" not in comps["VenueComponent"]


def test_add_mercenary_never_copies_host_body_type():
    """A follower with ``BodyType`` makes the game build ``{config}_{M/F}``
    and crash on a missing ``Configs.Characters`` key.  Game-created followers
    serialize with no ``BodyType``, so the avatar we inject must match."""
    summary = {"runID": "merc-run", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "H", "ConfigName": "HUNTER", "Things": []},
                    "PlayerComponent": {"IsPlayer": True},
                    "AvatarComponent": {
                        "BodyType": "F",
                        "PrimaryColor": "112233",
                        "SkinColorOverride": "X",
                    },
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    spec = {"config_name": "MERC_A_BASIC_00", "start_things": []}
    modified, ok, guid = add_mercenary(blob, "hero-1", spec)
    assert ok is True
    run2 = parse_ftk2(modified)["json"]
    av = [e for e in run2["Entities"] if e["Guid"] == guid][0]["Components"]["AvatarComponent"]
    assert "BodyType" not in av
    assert set(av.keys()) == set(editor._DEFAULT_MERC_AVATAR.keys())
    assert av["PrimaryColor"] == "112233"
    assert av["SkinColorOverride"] == "X"


def test_add_mercenary_injects_default_position_when_missing():
    summary = {"runID": "merc-run", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "H", "ConfigName": "HUNTER", "Things": []},
                    "PlayerComponent": {"IsPlayer": True},
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    spec = {"config_name": "MERC_A_BASIC_00", "start_things": []}
    modified, ok, guid = add_mercenary(blob, "hero-1", spec)
    assert ok is True
    run2 = parse_ftk2(modified)["json"]
    comps = [e for e in run2["Entities"] if e["Guid"] == guid][0]["Components"]
    assert comps["AdventureComponent"]["MapID"] == ""
    assert "TilePosition" in comps["VenueComponent"]


def test_add_mercenary_requires_player_host(sample_run_bytes):
    spec = {"config_name": "MERC_A_BASIC_00", "start_health": 10, "start_things": []}
    modified, ok, guid = add_mercenary(sample_run_bytes, "hero-1", spec)
    assert ok is False
    assert modified is sample_run_bytes
    assert guid == ""


def test_add_mercenary_unknown_host_fails():
    modified, ok, guid = add_mercenary(_merc_run_blob(), "ghost", {"config_name": "MERC_A_BASIC_00"})
    assert ok is False
    assert modified == _merc_run_blob()
    assert guid == ""


def test_add_mercenary_blank_or_missing_config_fails():
    blob = _merc_run_blob()
    modified, ok, guid = add_mercenary(blob, "hero-1", {})
    assert ok is False
    assert modified is blob
    assert guid == ""


def test_add_mercenary_not_gamerun_fails(sample_user_obj):
    blob = encrypt_ftk2_text(json.dumps(sample_user_obj, indent=2) + "\n")
    modified, ok, guid = add_mercenary(blob, "hero-1", {"config_name": "MERC_A"})
    assert ok is False
    assert modified is blob
    assert guid == ""


def test_swap_character_class_changes_config():
    modified, ok = swap_character_class(_merc_run_blob(), "hero-1", "BLACKSMITH")
    assert ok is True
    cc = parse_ftk2(modified)["json"]["Entities"][0]["Components"]["CharacterComponent"]
    assert cc["ConfigName"] == "BLACKSMITH"


def test_swap_character_class_unknown_guid_fails():
    blob = _merc_run_blob()
    modified, ok = swap_character_class(blob, "nope", "BLACKSMITH")
    assert ok is False
    assert modified is blob


def test_swap_character_class_blank_config_fails():
    blob = _merc_run_blob()
    modified, ok = swap_character_class(blob, "hero-1", "")
    assert ok is False
    assert modified is blob


def test_swap_character_class_duplicate_guid_fails():
    run = {
        "Entities": [
            _char_entity("hero-1", "HUNTER", []),
            _char_entity("hero-1", "MAGE", []),
        ]
    }
    blob = _run_blob(run, {"runID": "r", "saveName": "Test"})
    modified, ok = swap_character_class(blob, "hero-1", "BLACKSMITH")
    assert ok is False
    assert modified is blob


def test_swap_character_class_not_gamerun_fails(sample_user_obj):
    blob = encrypt_ftk2_text(json.dumps(sample_user_obj, indent=2) + "\n")
    modified, ok = swap_character_class(blob, "hero-1", "BLACKSMITH")
    assert ok is False
    assert modified is blob


def test_add_pet_creates_companion_with_kibble():
    spec = {
        "type_args": "COMPANION_WOLF_01",
        "config_name": "COMPANION_WOLF_BASIC_06",
        "contract_rounds": 0,
        "start_health": 96,
        "start_focus": 1,
        "start_things": [],
    }
    modified, ok, guid = add_pet(_merc_run_blob(), "hero-1", spec)
    assert ok is True
    assert guid

    run = parse_ftk2(modified)["json"]
    entities = run["Entities"]
    assert len(entities) == 2
    pet = [e for e in entities if e["Guid"] == guid]
    assert len(pet) == 1
    cc = pet[0]["Components"]["CharacterComponent"]
    assert cc["ConfigName"] == "COMPANION_WOLF_BASIC_06"
    assert cc["CharacterType"] == "COMPANION"
    assert cc["TypeArgs"] == "COMPANION_WOLF_01"
    assert cc["CurrentHealth"] == 96
    assert cc["CurrentFocus"] == 1
    assert cc["Equipped"]["MAIN_HAND"] == ""  # companions carry no gear
    by_name = {t["ConfigName"]: t for t in cc["Things"]}
    assert by_name["TOOL_KIBBLE_01"]["_stackCount"] == 50
    assert by_name["XP"]["_stackCount"] == 0

    followers = run["PlayerFollowers"]
    assert followers["hero-1"] == {"FollowerID": guid, "RoundsToExpire": 0}


def _positioned_run_blob() -> bytes:
    """A run with one player carrying a hex position and a venue tile."""
    summary = {"runID": "pet-run", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Host",
                        "ConfigName": "HUNTER",
                        "Things": [],
                    },
                    "PlayerComponent": {"IsPlayer": True},
                    "AvatarComponent": {"PrimaryColor": "AABBCC"},
                    "AdventureComponent": {
                        "HexPosition": {"Item1": 5, "Item2": 7},
                        "MapID": "MAP_1",
                    },
                    "VenueComponent": {
                        "TilePosition": {"Item1": 3, "Item2": 2},
                        "TileSize": {"Item1": 1, "Item2": 1},
                        "OccupiedTiles": [{"Item1": 3, "Item2": 2}],
                    },
                },
            }
        ]
    }
    return encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")


def test_add_pet_is_placed_beside_the_host():
    """A bound follower the game can actually draw needs the host's hex/map
    plus its own venue tile.  Written without them the pet is alive in the
    save but never appears on the map (an *unbound* recruit template is the
    only shape the game stores unplaced)."""
    spec = {"config_name": "COMPANION_A_BASIC_00", "start_things": []}
    modified, ok, guid = add_pet(_positioned_run_blob(), "hero-1", spec)
    assert ok is True
    run = parse_ftk2(modified)["json"]
    host = [e for e in run["Entities"] if e["Guid"] == "hero-1"][0]
    comps = [e for e in run["Entities"] if e["Guid"] == guid][0]["Components"]
    assert "CharacterComponent" in comps
    assert "AIComponent" in comps
    assert "AvatarComponent" in comps
    assert comps["AdventureComponent"] == host["Components"]["AdventureComponent"]
    venue = comps["VenueComponent"]
    host_tile = host["Components"]["VenueComponent"]["TilePosition"]
    assert venue["TilePosition"] != host_tile
    assert venue["TilePosition"]["Item2"] == host_tile["Item2"]
    assert venue["OccupiedTiles"] == [venue["TilePosition"]]


def test_add_pet_placement_does_not_mutate_the_host():
    spec = {"config_name": "COMPANION_A_BASIC_00", "start_things": []}
    modified, ok, guid = add_pet(_positioned_run_blob(), "hero-1", spec)
    assert ok is True
    run = parse_ftk2(modified)["json"]
    host = [e for e in run["Entities"] if e["Guid"] == "hero-1"][0]
    assert host["Components"]["VenueComponent"]["TilePosition"] == {
        "Item1": 3,
        "Item2": 2,
    }
    assert host["Components"]["AdventureComponent"]["HexPosition"] == {
        "Item1": 5,
        "Item2": 7,
    }


def test_repair_follower_placement_fixes_an_invisible_pet():
    """A pet bound without placement (written by an older editor) is
    back-filled from its host so the game can draw it."""
    summary = {"runID": "r", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "H", "ConfigName": "HUNTER"},
                    "PlayerComponent": {"IsPlayer": True},
                    "AvatarComponent": {"PrimaryColor": "AABBCC"},
                    "AdventureComponent": {
                        "HexPosition": {"Item1": 5, "Item2": 7},
                        "MapID": "MAP_1",
                    },
                    "VenueComponent": {
                        "TilePosition": {"Item1": 3, "Item2": 2},
                        "TileSize": {"Item1": 1, "Item2": 1},
                        "OccupiedTiles": [{"Item1": 3, "Item2": 2}],
                    },
                },
            },
            {
                "Guid": "pet-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Pup",
                        "ConfigName": "COMPANION_BAT_BASIC_02",
                        "CharacterType": "COMPANION",
                        "Things": [],
                    },
                    "AIComponent": {},
                    "AvatarComponent": {"PrimaryColor": "010203"},
                },
            },
        ],
        "PlayerFollowers": {"hero-1": {"FollowerID": "pet-1", "RoundsToExpire": 0}},
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok, repaired = repair_follower_placement(blob)
    assert ok is True
    assert repaired == ["pet-1"]
    out = parse_ftk2(modified)["json"]
    pet = [e for e in out["Entities"] if e["Guid"] == "pet-1"][0]["Components"]
    assert pet["AdventureComponent"]["MapID"] == "MAP_1"
    assert pet["AdventureComponent"]["HexPosition"] == {"Item1": 5, "Item2": 7}
    assert pet["VenueComponent"]["TilePosition"] == {"Item1": 4, "Item2": 2}
    # the host keeps its own tile
    host = [e for e in out["Entities"] if e["Guid"] == "hero-1"][0]["Components"]
    assert host["VenueComponent"]["TilePosition"] == {"Item1": 3, "Item2": 2}
    # idempotent: a second pass has nothing left to do
    again, ok2, repaired2 = repair_follower_placement(modified)
    assert ok2 is True
    assert repaired2 == []


def test_repair_follower_placement_skips_healthy_and_orphan_bindings():
    blob = _follower_run_blob()  # merc-1 is bound but has no placement
    modified, ok, repaired = repair_follower_placement(blob)
    assert ok is True
    assert repaired == ["merc-1"]

    run = parse_ftk2(modified)["json"]
    again, ok2, repaired2 = repair_follower_placement(modified)
    assert ok2 is True
    assert repaired2 == []


def test_repair_follower_placement_fails_closed_on_a_user_save():
    blob = encrypt_ftk2_text(json.dumps({"UserData": {}}))
    modified, ok, repaired = repair_follower_placement(blob)
    assert ok is False
    assert repaired == []
    assert modified == blob


def test_add_pet_never_copies_host_body_type():
    """Same crash guard as the mercenary: a companion must not inherit the
    host's player ``BodyType``, or the game queries ``Characters[config_F]``."""
    summary = {"runID": "pet-run", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "H", "ConfigName": "HUNTER", "Things": []},
                    "PlayerComponent": {"IsPlayer": True},
                    "AvatarComponent": {"BodyType": "M", "PrimaryColor": "FFEEDD"},
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    spec = {"config_name": "COMPANION_A_BASIC_00", "start_things": []}
    modified, ok, guid = add_pet(blob, "hero-1", spec)
    assert ok is True
    run2 = parse_ftk2(modified)["json"]
    av = [e for e in run2["Entities"] if e["Guid"] == guid][0]["Components"]["AvatarComponent"]
    assert "BodyType" not in av
    assert set(av.keys()) == set(editor._DEFAULT_MERC_AVATAR.keys())
    assert av["PrimaryColor"] == "FFEEDD"


def test_add_pet_requires_player_host(sample_run_bytes):
    spec = {"config_name": "COMPANION_A_BASIC_00", "start_things": []}
    modified, ok, guid = add_pet(sample_run_bytes, "hero-1", spec)
    assert ok is False
    assert modified is sample_run_bytes
    assert guid == ""


def test_add_pet_unknown_host_fails():
    spec = {"config_name": "COMPANION_A_BASIC_00", "start_things": []}
    blob = _merc_run_blob()
    modified, ok, guid = add_pet(blob, "ghost", spec)
    assert ok is False
    assert modified is blob
    assert guid == ""


def test_add_pet_blank_config_fails():
    blob = _merc_run_blob()
    modified, ok, guid = add_pet(blob, "hero-1", {})
    assert ok is False
    assert modified is blob
    assert guid == ""


def test_add_pet_not_gamerun_fails(sample_user_obj):
    blob = encrypt_ftk2_text(json.dumps(sample_user_obj, indent=2) + "\n")
    modified, ok, guid = add_pet(blob, "hero-1", {"config_name": "COMPANION_A"})
    assert ok is False
    assert modified is blob
    assert guid == ""


def _follower_run_blob() -> bytes:
    """A run with one player host plus a mercenary and a companion follower."""
    summary = {"runID": "follower-run", "saveName": "F"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "Host", "ConfigName": "HUNTER"},
                    "PlayerComponent": {"IsPlayer": True},
                },
            },
            {
                "Guid": "merc-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Gunny",
                        "ConfigName": "MERC_GUN_BASIC_06",
                        "CharacterType": "MERCENARY",
                    }
                },
            },
            {
                "Guid": "pet-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "Pup",
                        "ConfigName": "COMPANION_A_BASIC_00",
                        "CharacterType": "COMPANION",
                    }
                },
            },
        ],
        "PlayerFollowers": {
            "hero-1": {"FollowerID": "merc-1", "RoundsToExpire": 6},
        },
    }
    return encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")


def test_remove_follower_drops_entity_and_binding():
    modified, ok = remove_follower(_follower_run_blob(), "merc-1")
    assert ok is True

    run = parse_ftk2(modified)["json"]
    assert [e["Guid"] for e in run["Entities"]] == ["hero-1", "pet-1"]
    assert "hero-1" not in run["PlayerFollowers"]


def test_remove_follower_removes_unbound_companion():
    modified, ok = remove_follower(_follower_run_blob(), "pet-1")
    assert ok is True
    run = parse_ftk2(modified)["json"]
    assert [e["Guid"] for e in run["Entities"]] == ["hero-1", "merc-1"]
    assert run["PlayerFollowers"]["hero-1"]["FollowerID"] == "merc-1"


def test_remove_follower_refuses_player_character():
    blob = _follower_run_blob()
    modified, ok = remove_follower(blob, "hero-1")
    assert ok is False
    assert modified is blob


def test_remove_follower_unknown_guid_fails():
    blob = _follower_run_blob()
    modified, ok = remove_follower(blob, "ghost")
    assert ok is False
    assert modified is blob


def test_remove_follower_refuses_untyped_unbound_entity():
    summary = {"runID": "follower-run", "saveName": "F"}
    run = {
        "Entities": [
            {
                "Guid": "npc-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "Smuggler", "ConfigName": "NPC_A"}
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok = remove_follower(blob, "npc-1")
    assert ok is False
    assert modified is blob


def test_remove_follower_duplicate_guid_fails():
    summary = {"runID": "follower-run", "saveName": "F"}
    run = {
        "Entities": [
            {"Guid": "merc-1", "Components": {"CharacterComponent": {"CharacterType": "MERCENARY"}}},
            {"Guid": "merc-1", "Components": {"CharacterComponent": {"CharacterType": "MERCENARY"}}},
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok = remove_follower(blob, "merc-1")
    assert ok is False
    assert modified is blob


def test_remove_follower_blank_guid_fails():
    blob = _follower_run_blob()
    modified, ok = remove_follower(blob, "")
    assert ok is False
    assert modified is blob


def test_remove_follower_not_gamerun_fails(sample_user_obj):
    blob = encrypt_ftk2_text(json.dumps(sample_user_obj, indent=2) + "\n")
    modified, ok = remove_follower(blob, "merc-1")
    assert ok is False
    assert modified is blob


def test_add_pet_refuses_host_that_already_has_a_follower():
    """PlayerFollowers is a map: one follower per host, so recruiting over an
    occupied slot would orphan the previous pet entity."""
    blob = _follower_run_blob()
    spec = {
        "type_args": "COMPANION_WOLF_01",
        "config_name": "COMPANION_WOLF_BASIC_06",
        "contract_rounds": 0,
        "start_health": 96,
        "start_focus": 1,
        "start_things": [],
    }
    modified, ok, guid = add_pet(blob, "hero-1", spec)
    assert ok is False
    assert guid == ""
    assert modified is blob

    run = parse_ftk2(modified)["json"]
    assert run["PlayerFollowers"]["hero-1"] == {
        "FollowerID": "merc-1",
        "RoundsToExpire": 6,
    }
    assert len(run["Entities"]) == 3


def test_add_mercenary_refuses_host_that_already_has_a_follower():
    blob = _follower_run_blob()
    spec = {
        "type_args": "MERC_ARCHER_01",
        "config_name": "MERC_ARCHER_BASIC_06",
        "contract_rounds": 6,
        "start_health": 120,
        "start_focus": 0,
        "start_things": [],
    }
    modified, ok, guid = add_mercenary(blob, "hero-1", spec)
    assert ok is False
    assert guid == ""
    assert modified is blob
    run = parse_ftk2(modified)["json"]
    assert run["PlayerFollowers"]["hero-1"]["FollowerID"] == "merc-1"
    assert len(run["Entities"]) == 3


def test_add_pet_allowed_after_the_slot_is_freed():
    blob = _follower_run_blob()
    freed, ok = remove_follower(blob, "merc-1")
    assert ok is True
    spec = {
        "type_args": "COMPANION_WOLF_01",
        "config_name": "COMPANION_WOLF_BASIC_06",
        "contract_rounds": 0,
        "start_health": 96,
        "start_focus": 1,
        "start_things": [],
    }
    modified, ok, guid = add_pet(freed, "hero-1", spec)
    assert ok is True
    run = parse_ftk2(modified)["json"]
    assert run["PlayerFollowers"]["hero-1"]["FollowerID"] == guid
    assert "merc-1" not in [e["Guid"] for e in run["Entities"]]


def test_add_pet_ignores_empty_follower_slot_entry():
    """An entry with no FollowerID is not a binding, so it must not block."""
    summary = {"runID": "r", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "H", "ConfigName": "HUNTER"},
                    "PlayerComponent": {"IsPlayer": True},
                },
            }
        ],
        "PlayerFollowers": {"hero-1": {"FollowerID": "", "RoundsToExpire": 0}},
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    spec = {"config_name": "COMPANION_A_BASIC_00", "start_things": []}
    modified, ok, guid = add_pet(blob, "hero-1", spec)
    assert ok is True
    run = parse_ftk2(modified)["json"]
    assert run["PlayerFollowers"]["hero-1"]["FollowerID"] == guid


def test_remove_follower_clears_dangling_binding():
    """A PlayerFollowers entry whose entity is gone must still be removable,
    otherwise the slot can never be freed or reused."""
    summary = {"runID": "r", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "H", "ConfigName": "HUNTER"},
                    "PlayerComponent": {"IsPlayer": True},
                },
            }
        ],
        "PlayerFollowers": {"hero-1": {"FollowerID": "ghost", "RoundsToExpire": 0}},
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok = remove_follower(blob, "ghost")
    assert ok is True
    out = parse_ftk2(modified)["json"]
    assert out["PlayerFollowers"] == {}
    assert [e["Guid"] for e in out["Entities"]] == ["hero-1"]


def test_remove_follower_dangling_still_guards_unknown_guid():
    """A guid referenced nowhere is still rejected (no entity, no binding)."""
    blob = _follower_run_blob()
    modified, ok = remove_follower(blob, "ghost-2")
    assert ok is False
    assert modified is blob


def test_give_carnival_wheel_piece_can_give_a_stack():
    """The config is Stacks:true, so a requested count is one stack entry."""
    blob = _merc_run_blob()
    modified, ok = give_carnival_wheel_piece(blob, "hero-1", count=2)
    assert ok is True
    run = parse_ftk2(modified)["json"]
    wedges = [
        t
        for e in run["Entities"]
        if e["Guid"] == "hero-1"
        for t in e["Components"]["CharacterComponent"]["Things"]
        if t["ConfigName"] == "MISC_WHEELPIECE_01"
    ]
    assert len(wedges) == 1
    assert wedges[0]["_stackCount"] == 2
    assert wedges[0]["CustomData"] == {"ID": "PLAYERS_FULL_HEAL"}


def test_give_carnival_wheel_piece_refuses_a_second_without_replace():
    blob = _merc_run_blob()
    once, ok = give_carnival_wheel_piece(blob, "hero-1")
    assert ok is True
    again, ok2 = give_carnival_wheel_piece(once, "hero-1")
    assert ok2 is False
    assert again == once


def test_give_carnival_wheel_piece_replace_sets_the_stack():
    blob = _merc_run_blob()
    once, ok = give_carnival_wheel_piece(blob, "hero-1")
    assert ok is True
    topped, ok2 = give_carnival_wheel_piece(once, "hero-1", count=2, replace=True)
    assert ok2 is True
    run = parse_ftk2(topped)["json"]
    wedges = [
        t
        for t in [e for e in run["Entities"] if e["Guid"] == "hero-1"][0]["Components"][
            "CharacterComponent"
        ]["Things"]
        if t["ConfigName"] == "MISC_WHEELPIECE_01"
    ]
    assert len(wedges) == 1
    assert wedges[0]["_stackCount"] == 2


def test_give_carnival_wheel_piece_rejects_a_bad_count():
    blob = _merc_run_blob()
    for bad in (0, -1, True, "2", 1.5):
        modified, ok = give_carnival_wheel_piece(blob, "hero-1", count=bad)
        assert ok is False, bad
        assert modified == blob


def test_scholarwort_has_its_own_floor_below_the_herb_one():
    """Scholar's Wort is a herb, but its floor (10) overrides herb_minimum."""
    summary = {"runID": "r", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "H",
                        "ConfigName": "HUNTER",
                        "Things": [
                            {"Id": "1", "ConfigName": "HERB_SCHOLARWORT_01", "Type": "ITEM", "_stackCount": 3},
                            {"Id": "2", "ConfigName": "HERB_HAG_BANE_01", "Type": "ITEM", "_stackCount": 3},
                        ],
                    },
                    "PlayerComponent": {"IsPlayer": True},
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok, updated = ensure_party_herb_tool_minimum(
        blob,
        ["hero-1"],
        minimum=10,
        herb_minimum=15,
        scholarwort_minimum=10,
    )
    assert ok is True
    # both stacks moved: wort to its own 10, the other herb to 15
    assert updated == 2
    things = {
        t["ConfigName"]: t["_stackCount"]
        for t in parse_ftk2(modified)["json"]["Entities"][0]["Components"][
            "CharacterComponent"
        ]["Things"]
    }
    assert things["HERB_SCHOLARWORT_01"] == 10
    assert things["HERB_HAG_BANE_01"] == 15


def test_scholarwort_floor_is_opt_in():
    """Without the opt-in it is just another herb at herb_minimum."""
    summary = {"runID": "r", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "H",
                        "ConfigName": "HUNTER",
                        "Things": [
                            {"Id": "1", "ConfigName": "HERB_SCHOLARWORT_01", "Type": "ITEM", "_stackCount": 3}
                        ],
                    },
                    "PlayerComponent": {"IsPlayer": True},
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok, updated = ensure_party_herb_tool_minimum(
        blob, ["hero-1"], minimum=10, herb_minimum=15
    )
    assert ok is True
    assert updated == 1
    things = parse_ftk2(modified)["json"]["Entities"][0]["Components"][
        "CharacterComponent"
    ]["Things"]
    assert things[0]["_stackCount"] == 15


def test_set_character_thing_stack_sets_an_absolute_count():
    summary = {"runID": "r", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "H",
                        "ConfigName": "HUNTER",
                        "Things": [
                            {"Id": "1", "ConfigName": "HERB_SCHOLARWORT_01", "Type": "ITEM", "_stackCount": 15},
                            {"Id": "2", "ConfigName": "HERB_HAG_BANE_01", "Type": "ITEM", "_stackCount": 2},
                        ],
                    },
                    "PlayerComponent": {"IsPlayer": True},
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    modified, ok = set_character_thing_stack(blob, "hero-1", "HERB_SCHOLARWORT_01", 10)
    assert ok is True
    things = {
        t["ConfigName"]: t["_stackCount"]
        for t in parse_ftk2(modified)["json"]["Entities"][0]["Components"][
            "CharacterComponent"
        ]["Things"]
    }
    assert things["HERB_SCHOLARWORT_01"] == 10
    assert things["HERB_HAG_BANE_01"] == 2  # untouched


def test_set_character_thing_stack_is_fail_closed():
    summary = {"runID": "r", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {"DisplayName": "H", "ConfigName": "HUNTER", "Things": []},
                    "PlayerComponent": {"IsPlayer": True},
                },
            }
        ]
    }
    blob = encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")
    # not held -> never created
    for args in (
        ("hero-1", "HERB_SCHOLARWORT_01", 10),   # absent stack
        ("nope", "HERB_SCHOLARWORT_01", 10),      # no such character
        ("hero-1", "HERB_SCHOLARWORT_01", 0),     # bad count
        ("hero-1", "", 10),                        # bad config
        ("hero-1", "HERB_SCHOLARWORT_01", "10"),   # bad count type
    ):
        guid, config, count = args
        modified, ok = set_character_thing_stack(blob, guid, config, count)
        assert ok is False, args
        assert modified == blob, args


def _two_hero_run_blob(things_a: list[dict], things_b: list[dict]) -> bytes:
    summary = {"runID": "r", "saveName": "M"}
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "A", "ConfigName": "HUNTER", "Things": things_a
                    },
                    "PlayerComponent": {"IsPlayer": True},
                },
            },
            {
                "Guid": "hero-2",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "B", "ConfigName": "HUNTER", "Things": things_b
                    },
                    "PlayerComponent": {"IsPlayer": True},
                },
            },
        ]
    }
    return encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")


def _things_by_config(blob: bytes, guid: str) -> dict[str, int]:
    entity = [e for e in parse_ftk2(blob)["json"]["Entities"] if e["Guid"] == guid][0]
    return {
        t["ConfigName"]: t.get("_stackCount")
        for t in entity["Components"]["CharacterComponent"]["Things"]
    }


def test_grant_thing_to_party_creates_and_raises():
    """Unlike a top-up, a grant gives the stack to a member who has none."""
    blob = _two_hero_run_blob(
        [{"Id": "1", "ConfigName": "HERB_SCHOLARWORT_01", "Type": "ITEM",
          "_stackCount": 2, "Expansion": "BASE"}],
        [],
    )
    modified, ok, changed = grant_thing_to_party(blob, ["hero-1", "hero-2"], "HERB_SCHOLARWORT_01", 15)
    assert ok is True
    assert changed == 2
    for guid in ("hero-1", "hero-2"):
        things = _things_by_config(modified, guid)
        assert things["HERB_SCHOLARWORT_01"] == 15
    # exactly one stack each, not a pile of entries
    for guid in ("hero-1", "hero-2"):
        entity = [e for e in parse_ftk2(modified)["json"]["Entities"] if e["Guid"] == guid][0]
        stacks = [
            t
            for t in entity["Components"]["CharacterComponent"]["Things"]
            if t["ConfigName"] == "HERB_SCHOLARWORT_01"
        ]
        assert len(stacks) == 1
        assert stacks[0]["Type"] == "ITEM"
        assert stacks[0]["Expansion"] == "BASE"
        assert stacks[0]["Id"]


def test_grant_thing_to_party_never_lowers_a_bigger_stack():
    blob = _two_hero_run_blob(
        [{"Id": "1", "ConfigName": "HERB_SCHOLARWORT_01", "Type": "ITEM",
          "_stackCount": 40, "Expansion": "BASE"}],
        [{"Id": "2", "ConfigName": "HERB_SCHOLARWORT_01", "Type": "ITEM",
          "_stackCount": 15, "Expansion": "BASE"}],
    )
    modified, ok, changed = grant_thing_to_party(blob, ["hero-1", "hero-2"], "HERB_SCHOLARWORT_01", 15)
    assert ok is True
    assert changed == 0
    assert modified == blob


def test_grant_thing_to_party_is_idempotent():
    blob = _two_hero_run_blob([], [])
    once, ok, changed = grant_thing_to_party(blob, ["hero-1", "hero-2"], "MISC_MIRROR_01", 15)
    assert ok is True
    assert changed == 2
    twice, ok2, changed2 = grant_thing_to_party(once, ["hero-1", "hero-2"], "MISC_MIRROR_01", 15)
    assert ok2 is True
    assert changed2 == 0
    assert twice == once


def test_grant_thing_to_party_skips_unknown_guids():
    blob = _two_hero_run_blob([], [])
    modified, ok, changed = grant_thing_to_party(blob, ["hero-1", "ghost"], "MISC_MIRROR_01", 15)
    assert ok is True
    assert changed == 1
    assert "MISC_MIRROR_01" in _things_by_config(modified, "hero-1")


def test_grant_thing_to_party_fails_closed():
    blob = _two_hero_run_blob([], [])
    for args in (
        ([], "MISC_MIRROR_01", 15),          # no targets
        (["hero-1"], "", 15),                # no config
        (["hero-1"], "MISC_MIRROR_01", 0),   # bad count
        (["hero-1"], "MISC_MIRROR_01", -3),  # bad count
        (["hero-1"], "MISC_MIRROR_01", "15"),# bad count type
    ):
        guids, config, count = args
        modified, ok, changed = grant_thing_to_party(blob, guids, config, count)
        assert ok is False, args
        assert changed == 0, args
        assert modified == blob, args
    # a User save is not a GameRun
    user = encrypt_ftk2_text(json.dumps({"PartyCharacters": []}))
    modified, ok, changed = grant_thing_to_party(user, ["hero-1"], "MISC_MIRROR_01", 15)
    assert ok is False
    assert modified == user


def test_consumable_catalog_covers_the_known_consumables():
    """Reads the game's Things/ configs; skips gear, currency and passives."""
    from ftk2_editor.viewmodel import consumable_catalog

    catalog = consumable_catalog()
    if not catalog:  # game assets not mounted in this environment
        return
    configs = {row["config"] for row in catalog}
    assert "HERB_SCHOLARWORT_01" in configs
    assert "MISC_MIRROR_01" in configs
    assert "MISC_WHEELPIECE_01" in configs  # no USEABLE tag, but has an ability
    assert "TOOL_KIBBLE_01" in configs
    assert not any(c.startswith("CURRENCY_") for c in configs)
    assert "XP" not in configs
    for row in catalog:
        assert row["name"], row
        assert row["class"] not in {"WEAPON", "ATTIRE", "TRAIT", "CURRENCY"}, row


def _reflection_run_blob(host_things: list[dict] | None = None) -> bytes:
    summary = {"runID": "r", "saveName": "M"}
    things = host_things if host_things is not None else [
        {"Id": "t1", "ConfigName": "CURRENCY_ADVENTURE", "Type": "ITEM", "_stackCount": 500},
        {"Id": "t2", "ConfigName": "XP", "Type": "PASSIVE", "_stackCount": 1200},
        {"Id": "t3", "ConfigName": "LANCE_BASIC_00", "Type": "EQUIPMENT", "_stackCount": 1},
        {"Id": "t4", "ConfigName": "HERB_GODSBEARD_01", "Type": "ITEM", "_stackCount": 15},
    ]
    run = {
        "Entities": [
            {
                "Guid": "hero-1",
                "Components": {
                    "CharacterComponent": {
                        "DisplayName": "DeathBro",
                        "ConfigName": "FALLENKNIGHT",
                        "CharacterType": "STANDARD",
                        "CurrentHealth": 107,
                        "CurrentFocus": 5,
                        "Things": things,
                        "Equipped": {
                            "MAIN_HAND": "t3",
                            "OFF_HAND": "t3",
                            "HELMET": "",
                            "TRINKET": "t-not-mirrored",
                        },
                        "BaseStatModifiers": {"FOC": 1},
                        "SkinEquipped": {"HELMET": "DEFAULT_NONE"},
                    },
                    "PlayerComponent": {"IsPlayer": True},
                    "AvatarComponent": {"PrimaryColor": "AABBCC", "BodyType": "F"},
                    "AdventureComponent": {
                        "HexPosition": {"Item1": 11, "Item2": 15},
                        "MapID": "SIDE_ADVENTURE_DARK_CARNIVAL",
                    },
                    "VenueComponent": {
                        "TilePosition": {"Item1": 3, "Item2": 2},
                        "TileSize": {"Item1": 1, "Item2": 1},
                        "OccupiedTiles": [{"Item1": 3, "Item2": 2}],
                    },
                },
            }
        ]
    }
    return encrypt_ftk2_text(f"//**{json.dumps(summary)}**//\n{json.dumps(run)}\n")


def _reflection_cc(blob: bytes, guid: str) -> dict:
    entity = [e for e in parse_ftk2(blob)["json"]["Entities"] if e["Guid"] == guid][0]
    return entity["Components"]["CharacterComponent"]


def test_add_evil_reflection_mirrors_the_host():
    modified, ok, guid = add_evil_reflection(_reflection_run_blob(), "hero-1")
    assert ok is True
    assert guid
    run = parse_ftk2(modified)["json"]
    cc = _reflection_cc(modified, guid)

    # the marker the game itself writes
    assert cc["TypeArgs"] == "COMPANION_REFLECTION"
    assert cc["Properties"] == ["EVIL", "REFLECTION"]
    assert cc["CharacterType"] == "COMPANION"
    # mirrors the host's own class and name
    assert cc["ConfigName"] == "FALLENKNIGHT"
    assert cc["DisplayName"] == "Evil DeathBro"
    # weaker than its host, like the real Carnival reflections (72-75% HP,
    # focus 3 on both reference samples)
    assert cc["CurrentHealth"] == 80  # int(107 * 0.75)
    assert cc["CurrentFocus"] == 3
    # no stat/skin overrides, even though the host carries them
    assert cc["BaseStatModifiers"] == {}
    assert cc["SkinEquipped"] == {}
    # every equipped slot resolves to a thing the reflection actually owns
    thing_ids = {t["Id"] for t in cc["Things"]}
    for slot, thing_id in cc["Equipped"].items():
        assert thing_id == "" or thing_id in thing_ids, (slot, thing_id)
    # bound, permanent
    assert run["PlayerFollowers"]["hero-1"] == {
        "FollowerID": guid,
        "RoundsToExpire": -1,
    }
    # placed beside the host, never on the host's own tile
    entity = [e for e in run["Entities"] if e["Guid"] == guid][0]
    assert entity["Components"]["AdventureComponent"] == {
        "HexPosition": {"Item1": 11, "Item2": 15},
        "MapID": "SIDE_ADVENTURE_DARK_CARNIVAL",
    }
    assert entity["Components"]["VenueComponent"]["TilePosition"] == {
        "Item1": 4,
        "Item2": 2,
    }
    # no PlayerComponent, and no BodyType (that would crash the game)
    assert "PlayerComponent" not in entity["Components"]
    assert "BodyType" not in entity["Components"]["AvatarComponent"]


def test_add_evil_reflection_never_mirrors_gold_or_xp():
    """Cloning the wallet counters would hand out a second body's gold."""
    modified, ok, guid = add_evil_reflection(_reflection_run_blob(), "hero-1")
    assert ok is True
    things = {t["ConfigName"]: t for t in _reflection_cc(modified, guid)["Things"]}
    assert things["CURRENCY_ADVENTURE"]["_stackCount"] == 0
    assert things["XP"]["_stackCount"] == 0
    # gear and consumables are mirrored, with fresh ids
    assert things["LANCE_BASIC_00"]["_stackCount"] == 1
    assert things["HERB_GODSBEARD_01"]["_stackCount"] == 15
    host_ids = {
        t["Id"] for t in _reflection_cc(_reflection_run_blob(), "hero-1")["Things"]
    }
    assert not ({t["Id"] for t in _reflection_cc(modified, guid)["Things"]} & host_ids)


def test_add_evil_reflection_remaps_equipped_slots_and_empties_the_rest():
    """Equipment ids are regenerated when the stacks are cloned, so a copied
    Equipped map would dangle at gear the reflection does not have."""
    modified, ok, guid = add_evil_reflection(_reflection_run_blob(), "hero-1")
    assert ok is True
    cc = _reflection_cc(modified, guid)
    by_id = {t["Id"]: t["ConfigName"] for t in cc["Things"]}
    # MAIN_HAND/OFF_HAND pointed at the host's t3 (LANCE_BASIC_00) and now
    # point at the reflection's own copy of it
    assert cc["Equipped"]["MAIN_HAND"] in by_id
    assert by_id[cc["Equipped"]["MAIN_HAND"]] == "LANCE_BASIC_00"
    assert cc["Equipped"]["OFF_HAND"] == cc["Equipped"]["MAIN_HAND"]
    # a slot whose item was not mirrored is emptied, never left dangling
    assert cc["Equipped"]["TRINKET"] == ""
    # and it is not the host's id
    assert cc["Equipped"]["MAIN_HAND"] != "t3"


def test_add_evil_reflection_strength_knobs():
    modified, ok, guid = add_evil_reflection(
        _reflection_run_blob(), "hero-1", health_ratio=1.0, focus_cap=None
    )
    assert ok is True
    cc = _reflection_cc(modified, guid)
    assert cc["CurrentHealth"] == 107
    assert cc["CurrentFocus"] == 5
    # a nonsense ratio is ignored rather than producing a 0-HP corpse
    modified, ok, guid = add_evil_reflection(
        _reflection_run_blob(), "hero-1", health_ratio=0
    )
    assert ok is True
    assert _reflection_cc(modified, guid)["CurrentHealth"] == 107


def test_add_evil_reflection_can_skip_the_inventory():
    modified, ok, guid = add_evil_reflection(
        _reflection_run_blob(), "hero-1", copy_inventory=False
    )
    assert ok is True
    things = {t["ConfigName"] for t in _reflection_cc(modified, guid)["Things"]}
    assert things == {"XP", "CURRENCY_ADVENTURE"}


def test_add_evil_reflection_refuses_an_occupied_slot():
    """Same rule as recruiting: never silently orphan the current follower."""
    blob = _follower_run_blob()
    modified, ok, guid = add_evil_reflection(blob, "hero-1")
    assert ok is False
    assert guid == ""
    assert modified == blob
    run = parse_ftk2(modified)["json"]
    assert run["PlayerFollowers"]["hero-1"]["FollowerID"] == "merc-1"


def test_add_evil_reflection_replace_binds_over_the_old_follower():
    replaced, ok, guid = add_evil_reflection(
        _follower_run_blob(), "hero-1", replace=True
    )
    assert ok is True
    run = parse_ftk2(replaced)["json"]
    assert run["PlayerFollowers"]["hero-1"]["FollowerID"] == guid
    cc = _reflection_cc(replaced, guid)
    assert cc["TypeArgs"] == "COMPANION_REFLECTION"
    assert cc["DisplayName"] == "Evil Host"


def test_add_evil_reflection_is_fail_closed():
    blob = _reflection_run_blob()
    modified, ok, guid = add_evil_reflection(blob, "")
    assert ok is False
    assert modified == blob
    modified, ok, guid = add_evil_reflection(blob, "ghost")
    assert ok is False
    assert modified == blob
    # a User save is not a GameRun
    user = encrypt_ftk2_text(json.dumps({"PartyCharacters": []}))
    modified, ok, guid = add_evil_reflection(user, "hero-1")
    assert ok is False
    assert modified == user


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
