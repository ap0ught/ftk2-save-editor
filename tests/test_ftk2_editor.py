"""Tests for the FTK2 save editor (XOR-encrypted JSON)."""

from __future__ import annotations

import json

import pytest

from ftk2_editor import (
    ENCRYPT_KEY,
    backup,
    decrypt_ftk2_bytes,
    dump_summary,
    edit_field,
    ensure_character_herb_tool_minimum,
    encrypt_ftk2_text,
    parse_ftk2,
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
    summary = {"runID": "run-123", "saveName": "Test Expedition", "difficulty": "normal"}
    text = f"//**{json.dumps(summary)}**//\n{json.dumps(run, indent=2)}\n"
    with_scrolls = encrypt_ftk2_text(text)

    modified, ok, updated = ensure_character_herb_tool_minimum(
        with_scrolls,
        "hero-1",
        minimum=10,
    )
    assert ok is True
    assert updated == 6  # herb + tool + drink + 2 scrolls + safetystone

    things = parse_ftk2(modified)["json"]["Entities"][0]["Components"]["CharacterComponent"]["Things"]
    by_name = {entry["ConfigName"]: entry["_stackCount"] for entry in things}
    assert by_name["SCROLL_TELEPORT_01"] == 10
    assert by_name["SCROLL_VISION_01"] == 10
    assert by_name["MISC_SAFETYSTONE_01"] == 10


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
