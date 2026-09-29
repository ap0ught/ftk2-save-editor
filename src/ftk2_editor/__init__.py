"""FTK2 save file parser and editor.

For The King II stores saves as UTF-8 text with a UTF-8 BOM, then
XOR-obfuscates each Unicode character with the repeating key from
``SaveGameHelper`` in ``FTK2.dll`` (``encryptString = "21398xa2"``).

Under the obfuscation the payload is indented System.Text.Json JSON
for ``UserData`` (``User.ftk2``) or a ``//**summary**//\\n`` +
``GameRunData`` JSON stream (``GameRuns/*.ftk2``).

See ``decompiled/FORMAT.md`` and ``decompiled/SaveGameHelper.cs``.
"""

from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Collection


# Key from SaveGameHelper.encryptString in FTK2.dll
ENCRYPT_KEY = "21398xa2"

FTK2_BOM = b"\xef\xbb\xbf"

FTK2_GAME_DIR = (
    Path.home()
    / ".local/share/Steam/steamapps/compatdata/1676840/pfx/drive_c"
    / "users/steamuser/AppData/LocalLow/IronOak Games/For The King II"
)
USER_SAVE = FTK2_GAME_DIR / "User.ftk2"
BACKUPS_DIR = FTK2_GAME_DIR / "Backups"
GAME_RUNS_DIR = FTK2_GAME_DIR / "GameRuns"

# Game install data: streaming "JSON~" configs (Followers.json, Characters.json,
# Things/*.json) under For The King II_Data/StreamingAssets/Assets/Configs/JSON~.
FTK2_ASSETS_DIR = (
    Path.home()
    / ".local/share/Steam/steamapps/common/For The King II"
    / "For The King II_Data"
    / "StreamingAssets"
    / "Assets"
    / "Configs"
    / "JSON~"
)


def xor_crypt(text: str, key: str = ENCRYPT_KEY) -> str:
    """XOR each character with the repeating key (encrypt == decrypt)."""
    if not key:
        raise ValueError("encrypt key must be non-empty")
    kl = len(key)
    return "".join(chr(ord(ch) ^ ord(key[i % kl])) for i, ch in enumerate(text))


def decrypt_ftk2_bytes(data: bytes, key: str = ENCRYPT_KEY) -> str:
    """Decrypt a ``.ftk2`` file body to plaintext (usually JSON)."""
    if data.startswith(FTK2_BOM):
        data = data[3:]
    return xor_crypt(data.decode("utf-8"), key)


def encrypt_ftk2_text(text: str, key: str = ENCRYPT_KEY, *, with_bom: bool = True) -> bytes:
    """Encrypt plaintext to a ``.ftk2`` byte payload (UTF-8, optional BOM)."""
    encrypted = xor_crypt(text, key)
    body = encrypted.encode("utf-8")
    return (FTK2_BOM + body) if with_bom else body


def load_user_json(data: bytes, key: str = ENCRYPT_KEY) -> dict[str, Any]:
    """Decrypt ``User.ftk2`` bytes and parse JSON into a dict."""
    plain = decrypt_ftk2_bytes(data, key)
    return json.loads(plain)


def dump_user_json(obj: dict[str, Any], *, indent: int = 2) -> str:
    """Serialize a UserData-like dict the way the game tends to write it."""
    # Game uses JsonHelper with indented JSON and \\r\\n on Windows/Proton.
    return json.dumps(obj, indent=indent, ensure_ascii=False) + "\n"


def parse_ftk2(data: bytes) -> dict[str, Any]:
    """Decrypt and parse a save; returns metadata plus JSON object when possible."""
    has_bom = data.startswith(FTK2_BOM)
    plain = decrypt_ftk2_bytes(data)
    stripped = plain.lstrip()
    result: dict[str, Any] = {
        "header": {
            "has_bom": has_bom,
            "format": "xor-json",
            "encrypt_key": ENCRYPT_KEY,
            "plaintext_prefix": plain[:80],
        },
        "file_size": len(data),
        "plaintext_size": len(plain),
        "json": None,
        "summary": None,
        "run_json_text": None,
        "parse_error": None,
    }

    if stripped.startswith("//**"):
        # GameRuns/*.ftk2: //**{summary}**//\\n{GameRunData...}
        end = plain.find("**//")
        if end != -1:
            summary_raw = plain[4:end]
            rest_start = end + 4
            if rest_start < len(plain) and plain[rest_start] == "\n":
                rest_start += 1
            elif rest_start + 1 < len(plain) and plain[rest_start : rest_start + 2] == "\r\n":
                rest_start += 2
            try:
                result["summary"] = json.loads(summary_raw)
            except json.JSONDecodeError as exc:
                result["parse_error"] = f"summary JSON: {exc}"
            result["run_json_text"] = plain[rest_start:]
            try:
                result["json"] = json.loads(plain[rest_start:])
            except json.JSONDecodeError as exc:
                # Full GameRunData can be huge / nested; keep text available
                if result["parse_error"] is None:
                    result["parse_error"] = f"run JSON: {exc}"
        else:
            result["parse_error"] = "missing **// summary delimiter"
        return result

    try:
        result["json"] = json.loads(plain)
    except json.JSONDecodeError as exc:
        result["parse_error"] = str(exc)
    return result


def dump_summary(result: dict[str, Any]) -> str:
    """Human-readable summary of a parsed save."""
    lines = [
        "=" * 60,
        "FTK2 Save File Summary",
        "=" * 60,
        f"\nFile size: {result.get('file_size', 0)} bytes",
        f"Plaintext size: {result.get('plaintext_size', 0)} bytes",
        f"Format: XOR-obfuscated JSON (key={ENCRYPT_KEY!r})",
        f"Has BOM: {result.get('header', {}).get('has_bom')}",
    ]

    if result.get("parse_error"):
        lines.append(f"Parse note: {result['parse_error']}")

    summary = result.get("summary")
    if isinstance(summary, dict):
        lines.append("\nRun summary:")
        for key in (
            "runID",
            "saveName",
            "difficulty",
            "adventureType",
            "version",
            "dateTime",
        ):
            if key in summary:
                lines.append(f"  {key}: {summary[key]}")

    obj = result.get("json")
    if isinstance(obj, dict):
        lines.append(f"\nTop-level JSON keys ({len(obj)}):")
        for key in sorted(obj.keys()):
            val = obj[key]
            if isinstance(val, dict):
                lines.append(f"  {key}: dict[{len(val)}]")
            elif isinstance(val, list):
                lines.append(f"  {key}: list[{len(val)}]")
            else:
                preview = repr(val)
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(f"  {key}: {preview}")

        local = obj.get("LocalStats")
        if isinstance(local, dict):
            interesting = [
                (k, v)
                for k, v in local.items()
                if any(
                    token in k.upper()
                    for token in ("LORE", "GOLD", "STAT", "UNLOCK", "CURRENCY")
                )
            ][:25]
            if interesting:
                lines.append("\nLocalStats sample (lore/gold/stat-ish):")
                for k, v in interesting:
                    lines.append(f"  {k}: {v}")

        unlocks = obj.get("NewLoreStoreUnlocks")
        if isinstance(unlocks, list):
            lines.append(f"\nNewLoreStoreUnlocks: {len(unlocks)}")
            for item in unlocks[:15]:
                lines.append(f"  - {item}")

    lines.append("")
    return "\n".join(lines)


def edit_field(data: bytes, field_name: str, new_value: str) -> tuple[bytes, bool]:
    """Set a top-level JSON field (or ``LocalStats.<name>``) and re-encrypt.

    ``new_value`` is parsed as JSON when possible (numbers, bools, null);
    otherwise kept as a string.
    """
    plain = decrypt_ftk2_bytes(data)
    if plain.lstrip().startswith("//**"):
        return data, False

    try:
        obj = json.loads(plain)
    except json.JSONDecodeError:
        return data, False

    try:
        parsed_value: Any = json.loads(new_value)
    except json.JSONDecodeError:
        parsed_value = new_value

    if field_name.startswith("LocalStats."):
        stat_key = field_name.split(".", 1)[1]
        stats = obj.setdefault("LocalStats", {})
        if not isinstance(stats, dict):
            return data, False
        stats[stat_key] = parsed_value
    elif field_name in obj or True:
        # Allow creating new top-level keys for experimentation
        obj[field_name] = parsed_value
    else:
        return data, False

    # Preserve original newline style when possible
    if "\r\n" in plain:
        text = json.dumps(obj, indent=2, ensure_ascii=False).replace("\n", "\r\n")
        if plain.endswith("\r\n"):
            text += "\r\n"
        elif plain.endswith("\n"):
            text += "\r\n"
    else:
        text = dump_user_json(obj).rstrip("\n")
        if plain.endswith("\n"):
            text += "\n"

    return encrypt_ftk2_text(text), True


def _split_gamerun_plain(plain: str) -> tuple[str, str, str] | None:
    """Return (summary_json_text, body_json_text, joiner) for a GameRun plaintext."""
    stripped = plain.lstrip()
    if not stripped.startswith("//**"):
        return None
    # Preserve any leading whitespace from original plain (usually none)
    start = plain.find("//**")
    end = plain.find("**//", start)
    if end < 0:
        return None
    summary = plain[start + 4 : end]
    rest = plain[end + 4 :]
    if rest.startswith("\r\n"):
        joiner = "\r\n"
        body = rest[2:]
    elif rest.startswith("\n"):
        joiner = "\n"
        body = rest[1:]
    else:
        joiner = "\n"
        body = rest
    return summary, body, joiner


def _dump_json_matching_newlines(obj: Any, sample_text: str) -> str:
    """Serialize JSON using CRLF if *sample_text* uses CRLF."""
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if "\r\n" in sample_text:
        text = text.replace("\n", "\r\n")
        if sample_text.endswith("\r\n") and not text.endswith("\r\n"):
            text += "\r\n"
    elif sample_text.endswith("\n") and not text.endswith("\n"):
        text += "\n"
    return text


def grant_thing_to_party(
    data: bytes,
    guids: list[str],
    config: str,
    count: int,
    *,
    thing_type: str = "ITEM",
    expansion: str = "BASE",
) -> tuple[bytes, bool, int]:
    """Top every party member in *guids* up to *count* of a stackable *config*.

    Unlike ``ensure_*_minimum``, a member who holds none of the item is
    *given* a fresh stack (fresh ``Id``, ``Type``/``Expansion`` as passed), so
    this is a grant rather than a top-up; a member already holding it has that
    stack raised to *count* when it is lower and left alone when it is higher.

    One decrypt/encrypt pass for the whole party (see
    ``ensure_party_herb_tool_minimum`` for the same shape).  Returns
    ``(new_data, ok, members_changed)``; ``ok`` is False (data unchanged) for a
    non-GameRun file, no guids, bad arguments, or a malformed save.
    """
    if not guids or not config or not thing_type or not expansion:
        return data, False, 0
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return data, False, 0

    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, 0
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, 0
    if not isinstance(run, dict):
        return data, False, 0

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False, 0
    for e in entities:
        if not isinstance(e, dict):
            return data, False, 0

    guid_set = {str(g) for g in guids}
    changed = 0
    for entity in entities:
        if str(entity.get("Guid")) not in guid_set:
            continue
        comps = entity.get("Components")
        if not isinstance(comps, dict):
            continue
        cc = comps.get("CharacterComponent")
        if not isinstance(cc, dict):
            continue
        things = cc.get("Things")
        if not isinstance(things, list):
            continue
        for thing in things:
            if not isinstance(thing, dict):
                continue
            if (
                thing.get("ConfigName") != config
                or thing.get("Type") != thing_type
                or thing.get("Expansion") != expansion
            ):
                continue
            try:
                current = int(thing.get("_stackCount") or 0)
            except (TypeError, ValueError):
                current = 0
            if current < count:
                thing["_stackCount"] = count
                changed += 1
            break
        else:
            things.append(
                {
                    "Id": str(uuid.uuid4()),
                    "ConfigName": config,
                    "Type": thing_type,
                    "_stackCount": count,
                    "Expansion": expansion,
                }
            )
            changed += 1

    if changed == 0:
        return data, True, 0

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, changed


def replace_character_thing(
    data: bytes,
    character_guid: str,
    thing_id: str,
    new_config: str,
) -> tuple[bytes, bool]:
    """Replace a Thing's ConfigName in a run character's inventory.

    Fail-closed: returns (data, False) if run structure is invalid,
    if character_guid/thing_id/new_config are empty, if Entities contains
    non-object entries, or if there are duplicate character GUIDs or
    duplicate Thing IDs for the target character.
    """
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False
    if not isinstance(run, dict) or not character_guid or not thing_id or not new_config:
        return data, False

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False

    # Fail-closed: no non-object entries in Entities
    for e in entities:
        if not isinstance(e, dict):
            return data, False

    # Find matching character (fail if duplicate GUIDs)
    matching_chars = [e for e in entities if e.get("Guid") == character_guid]
    if len(matching_chars) != 1:
        return data, False
    entity = matching_chars[0]

    comps = entity.get("Components")
    if not isinstance(comps, dict):
        return data, False
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return data, False
    things = cc.get("Things")
    if not isinstance(things, list):
        return data, False

    # Fail-closed: no non-object entries in Things
    for t in things:
        if not isinstance(t, dict):
            return data, False

    # Find matching thing (fail if duplicate Thing IDs)
    matching_things = [t for t in things if t.get("Id") == thing_id]
    if len(matching_things) != 1:
        return data, False

    matching_things[0]["ConfigName"] = new_config

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True


def add_character_thing(
    data: bytes,
    character_guid: str,
    config: str,
    thing_type: str,
    expansion: str = "BASE",
) -> tuple[bytes, bool]:
    """Append an unequipped item to a run character's inventory.

    Fail-closed: returns (data, False) if run structure is invalid,
    if character_guid/config/thing_type/expansion are empty, if Entities
    contains non-object entries, or if there are duplicate character GUIDs.
    """
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False
    if (
        not isinstance(run, dict)
        or not character_guid
        or not config
        or not thing_type
        or not expansion
    ):
        return data, False

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False

    # Fail-closed: no non-object entries in Entities
    for e in entities:
        if not isinstance(e, dict):
            return data, False

    # Find matching character (fail if duplicate GUIDs)
    matching_chars = [e for e in entities if e.get("Guid") == character_guid]
    if len(matching_chars) != 1:
        return data, False
    entity = matching_chars[0]

    comps = entity.get("Components")
    if not isinstance(comps, dict):
        return data, False
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return data, False
    things = cc.get("Things")
    if not isinstance(things, list):
        return data, False

    # Fail-closed: no non-object entries in Things
    for t in things:
        if not isinstance(t, dict):
            return data, False

    things.append(
        {
            "Id": str(uuid.uuid4()),
            "ConfigName": config,
            "Type": thing_type,
            "_stackCount": 1,
            "Expansion": expansion,
        }
    )
    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True


def add_character_thing_stack(
    data: bytes,
    character_guid: str,
    config: str,
    count: int,
    *,
    thing_type: str = "ITEM",
    expansion: str = "BASE",
) -> tuple[bytes, bool, int]:
    """Add *count* of a stackable item to a run character, merging stacks.

    ``add_character_thing`` always appends a single unit with a fresh ``Id``,
    which is right for equipment but wrong for a stackable like
    ``MISC_MIRROR_01``.  This bumps the ``_stackCount`` of an existing matching
    Thing instead, and only appends a new entry when the character carries none,
    so repeated calls accumulate instead of littering the inventory.

    Returns ``(new_data, ok, total_count)``; ``ok`` is False (data unchanged)
    for a non-GameRun file, a missing/ambiguous character, bad arguments, or a
    malformed ``Things`` list.
    """
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, 0
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, 0
    if (
        not isinstance(run, dict)
        or not character_guid
        or not config
        or not thing_type
        or not expansion
    ):
        return data, False, 0
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return data, False, 0

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False, 0
    for e in entities:
        if not isinstance(e, dict):
            return data, False, 0

    matching_chars = [e for e in entities if e.get("Guid") == character_guid]
    if len(matching_chars) != 1:
        return data, False, 0
    comps = matching_chars[0].get("Components")
    if not isinstance(comps, dict):
        return data, False, 0
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return data, False, 0
    things = cc.get("Things")
    if not isinstance(things, list):
        return data, False, 0
    for t in things:
        if not isinstance(t, dict):
            return data, False, 0

    # Merge into the first matching stack; leave any duplicates alone.
    total = 0
    for thing in things:
        if (
            thing.get("ConfigName") == config
            and thing.get("Type") == thing_type
            and thing.get("Expansion") == expansion
        ):
            try:
                current = int(thing.get("_stackCount") or 0)
            except (TypeError, ValueError):
                current = 0
            total = current + count
            thing["_stackCount"] = total
            break
    else:
        total = count
        things.append(
            {
                "Id": str(uuid.uuid4()),
                "ConfigName": config,
                "Type": thing_type,
                "_stackCount": count,
                "Expansion": expansion,
            }
        )

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, total


def give_carnival_wheel_piece(
    data: bytes,
    character_guid: str,
    *,
    reward: str = "PLAYERS_FULL_HEAL",
    count: int = 1,
    replace: bool = False,
) -> tuple[bytes, bool]:
    """Give Carnival Wheel wedges (``MISC_WHEELPIECE_01``) to a run character.

    Writes the exact thing shape the game uses for a Wheel-of-Death reward
    (``CustomData.ID`` = ``reward``).  The config is ``Stacks: true``, so
    *count* wedges live in a single stack rather than as separate entries.

    A hero who already holds a wedge is a fail-closed ``(data, False)`` unless
    *replace* is set, which sets the existing stack to *count* instead.
    Fail-closed: returns ``(data, False)`` on non-GameRun saves, invalid
    structure, duplicate character GUIDs, a *count* below 1, or an existing
    wedge with *replace* unset.
    """
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False
    if not isinstance(run, dict) or not character_guid or not reward:
        return data, False
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return data, False

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False
    for e in entities:
        if not isinstance(e, dict):
            return data, False

    matching_chars = [e for e in entities if e.get("Guid") == character_guid]
    if len(matching_chars) != 1:
        return data, False
    entity = matching_chars[0]

    comps = entity.get("Components")
    if not isinstance(comps, dict):
        return data, False
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return data, False
    things = cc.get("Things")
    if not isinstance(things, list):
        return data, False
    for t in things:
        if not isinstance(t, dict):
            return data, False
        if t.get("ConfigName") != "MISC_WHEELPIECE_01":
            continue
        if not replace:
            return data, False  # already holds one
        t["_stackCount"] = count  # top the existing stack up / down
        break
    else:
        things.append(
            {
                "Id": str(uuid.uuid4()),
                "ConfigName": "MISC_WHEELPIECE_01",
                "Type": "ITEM",
                "_stackCount": count,
                "CustomData": {"ID": reward},
                "Expansion": "BASE",
            }
        )
    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True


def set_character_thing_stack(
    data: bytes,
    character_guid: str,
    config_name: str,
    count: int,
) -> tuple[bytes, bool]:
    """Set an existing Thing stack in a run character to an absolute *count*.

    The top-up helpers only ever *raise* a stack, so a floor change (e.g.
    Scholar's Wort from 15 down to its 10) cannot be applied by topping up —
    that needs a setter.  Only a stack the character already holds is touched;
    nothing is created or destroyed.

    Fail-closed: returns ``(data, False)`` on non-GameRun saves, invalid
    structure, a missing/duplicate character GUID, a non-positive *count*, or
    when the character holds no such stack.
    """
    if not character_guid or not config_name:
        return data, False
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return data, False
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False
    if not isinstance(run, dict):
        return data, False

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False
    for e in entities:
        if not isinstance(e, dict):
            return data, False

    matching = [e for e in entities if e.get("Guid") == character_guid]
    if len(matching) != 1:
        return data, False
    comps = matching[0].get("Components")
    if not isinstance(comps, dict):
        return data, False
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return data, False
    things = cc.get("Things")
    if not isinstance(things, list):
        return data, False

    wanted = config_name.upper()
    hits = [
        thing
        for thing in things
        if isinstance(thing, dict) and str(thing.get("ConfigName") or "").upper() == wanted
    ]
    if len(hits) != 1:
        return data, False  # absent, or ambiguous (two stacks of one config)
    hits[0]["_stackCount"] = count

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True


def set_character_gold(
    data: bytes,
    character_guid: str,
    gold: int,
    *,
    currency: str = "CURRENCY_ADVENTURE",
) -> tuple[bytes, bool]:
    """Set a run character's wallet gold (``CURRENCY_ADVENTURE`` stack) and re-encrypt.

    Only works on GameRun ``.ftk2`` files (``//**summary**//`` + ``GameRunData``).
    """
    if gold < 0:
        raise ValueError("gold must be >= 0")
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False

    found = False
    for entity in entities:
        if entity.get("Guid") != character_guid:
            continue
        comps = entity.setdefault("Components", {})
        cc = comps.setdefault("CharacterComponent", {})
        things = cc.setdefault("Things", [])
        if not isinstance(things, list):
            return data, False
        for thing in things:
            if isinstance(thing, dict) and thing.get("ConfigName") == currency:
                thing["_stackCount"] = int(gold)
                thing.setdefault("Type", "ITEM")
                found = True
                break
        if not found:
            things.append(
                {
                    "Id": str(uuid.uuid4()),
                    "ConfigName": currency,
                    "Type": "ITEM",
                    "_stackCount": int(gold),
                    "Expansion": "BASE",
                }
            )
            found = True
        break

    if not found:
        return data, False

    new_body = _dump_json_matching_newlines(run, body_text)
    # Keep summary bytes unchanged when possible (avoid reformatting)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True


def set_carnival_tickets(
    data: bytes,
    amount: int,
    *,
    ticket: str = "MISC_CARNIVALTICKET_01",
) -> tuple[bytes, bool]:
    """Set the campaign's shared Carnival Ticket pool (``ItemPools``) and re-encrypt.

    GameRun files only (``//**summary**//`` + ``GameRunData``).  Returns
    ``(data, False)`` when the save is not a GameRun or has no ``ItemPools``
    dict.  The Dark Carnival dungeon branches gate on this pool
    (``DungeonState.ChoiceStack[*].KeyItem`` / ``KeyAmount``).
    """
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError("amount must be a non-negative integer")
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False
    if not isinstance(run, dict):
        return data, False
    pools = run.get("ItemPools")
    if not isinstance(pools, dict):
        return data, False
    pools[ticket] = int(amount)
    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True


def rename_party_member(
    data: bytes,
    new_name: str,
    *,
    guid: str | None = None,
    current_name: str | None = None,
) -> tuple[bytes, bool]:
    """Rename a party character's ``CharacterComponent.DisplayName``.

    Works on both GameRun files (``//**summary**//`` + ``GameRunData``) and
    User.ftk2 (``PartyCharacters``). Identify the character either by its
    unique ``Guid`` (guid wins when both are given) or by its exact current
    ``DisplayName``. Fail-closed: returns ``(data, False)`` when the match is
    missing or not unique, when ``new_name`` is blank, or when the save /
    character structure is invalid.
    """
    modified, ok, _ = _rename_party_member(
        data, new_name, guid=guid, current_name=current_name
    )
    return modified, ok


def _rename_party_member(
    data: bytes,
    new_name: str,
    *,
    guid: str | None,
    current_name: str | None,
) -> tuple[bytes, bool, str | None]:
    """Parse-once rename that also returns the resolved character GUID.

    A single decrypt + parse for both matching and mutation; callers that also
    need the GUID (roster sync) use this instead of re-parsing the payload.
    Fail-closed: returns ``(data, False, None)`` on invalid input, decode /
    decryption errors, a missing or non-unique match, or a malformed save
    structure.  ``*guid*`` resolves to itself when it is supplied and present.
    """
    if not isinstance(new_name, str) or not new_name.strip():
        return data, False, None
    if not guid and not current_name:
        return data, False, None

    try:
        plain = decrypt_ftk2_bytes(data)
    except UnicodeDecodeError:
        return data, False, None
    parts = _split_gamerun_plain(plain)
    if parts is not None:
        summary_text, body_text, joiner = parts
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            return data, False, None
        sample_text = body_text
    else:
        try:
            payload = json.loads(plain)
        except json.JSONDecodeError:
            return data, False, None
        summary_text = plain
        joiner = None
        sample_text = plain

    if not isinstance(payload, dict):
        return data, False, None
    if "Entities" in payload:
        entities = payload["Entities"]
    elif "PartyCharacters" in payload:
        entities = payload["PartyCharacters"]
    else:
        return data, False, None
    if not isinstance(entities, list):
        return data, False, None

    resolved: str | None = guid
    matching: list[dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            return data, False, None
        if guid:
            if entity.get("Guid") == guid:
                matching.append(entity)
            continue
        comps = entity.get("Components")
        if not isinstance(comps, dict):
            continue
        cc = comps.get("CharacterComponent")
        if isinstance(cc, dict) and cc.get("DisplayName") == current_name:
            matching.append(entity)
    if len(matching) != 1:
        return data, False, None
    if not guid:
        resolved = matching[0].get("Guid")

    comps = matching[0].get("Components")
    if not isinstance(comps, dict):
        return data, False, None
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return data, False, None
    cc["DisplayName"] = new_name

    new_body = _dump_json_matching_newlines(payload, sample_text)
    if joiner is not None:
        new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    else:
        new_plain = new_body
    return encrypt_ftk2_text(new_plain), True, resolved


def _sync_roster_names(obj: dict[str, Any], new_name: str, guid: str) -> bool:
    """Update ``DisplayName`` for *guid* in a UserData dict's roster lists."""
    changed = False
    for key in ("PartyCharacters", "LastRunCharacters"):
        entries = obj.get(key)
        if not isinstance(entries, list):
            continue
        for entity in entries:
            if not isinstance(entity, dict) or entity.get("Guid") != guid:
                continue
            comps = entity.get("Components")
            if not isinstance(comps, dict):
                continue
            cc = comps.get("CharacterComponent")
            if not isinstance(cc, dict):
                continue
            cc["DisplayName"] = new_name
            changed = True
    return changed


def rename_party_member_synced(
    data: bytes,
    new_name: str,
    *,
    guid: str | None = None,
    current_name: str | None = None,
    user_data: bytes | None = None,
) -> tuple[bytes, bool, bytes | None]:
    """Rename a party member and sync the name into a User save roster.

    Wraps :func:`rename_party_member`; when *user_data* (User.ftk2 bytes) is
    given, the resolved GUID's ``DisplayName`` is also updated in both
    ``PartyCharacters`` and ``LastRunCharacters`` so menus pick up the change.
    Returns ``(data', ok, user_data')`` where ``user_data'`` is None when the
    rename failed or there was nothing to sync, otherwise the patched User
    bytes.  On failure the original *data* is returned unchanged.
    """
    if not isinstance(new_name, str) or not new_name.strip():
        return data, False, None
    modified, ok, resolved = _rename_party_member(
        data, new_name, guid=guid, current_name=current_name
    )
    if not ok:
        return data, False, None
    if user_data is None or not resolved:
        return modified, True, None
    try:
        user_plain = decrypt_ftk2_bytes(user_data)
    except UnicodeDecodeError:
        return modified, True, None
    try:
        user = json.loads(user_plain)
    except json.JSONDecodeError:
        return modified, True, None
    if not isinstance(user, dict):
        return modified, True, None
    if _sync_roster_names(user, new_name, resolved):
        patched = encrypt_ftk2_text(_dump_json_matching_newlines(user, user_plain))
        return modified, True, patched
    return modified, True, None


def ensure_character_herb_tool_minimum(
    data: bytes,
    character_guid: str,
    *,
    minimum: int = 10,
    herb_minimum: int | None = None,
    kibble_minimum: int | None = None,
    godsbeard_minimum: int | None = None,
    scholarwort_minimum: int | None = None,
    pet_owners: Collection[str] | None = None,
    healers: Collection[str] | None = None,
) -> tuple[bytes, bool, int]:
    """Ensure a character has minimum consumable stacks, including safetystones and thrown items.

    Matches Things whose ``ConfigName`` contains HERB / TOOL / DRINK / SCROLL /
    SAFETYSTONE / THROW / ORB / CANDY / MISC_INK (or whose ``Type`` is HERB / TOOL),
    topping each stack below its target up.  The generic target is *minimum*;
    optional *herb_minimum* / *kibble_minimum* / *godsbeard_minimum* override it
    for herbs, for a pet owner's kibble and for a healer's godsbeard respectively.
    *pet_owners* / *healers* are the guids those conditional floors apply to.
    Returns ``(new_data, ok, updated_entries)`` where ``ok`` means the character
    was found in a GameRun file.
    """
    if minimum < 0:
        raise ValueError("minimum must be >= 0")

    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, 0
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, 0

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False, 0

    updated_entries = 0
    found_character = False
    for entity in entities:
        if entity.get("Guid") != character_guid:
            continue
        found_character = True
        comps = entity.get("Components") or {}
        cc = comps.get("CharacterComponent") or {}
        things = cc.get("Things") or []
        if not isinstance(things, list):
            return data, False, 0

        for thing in things:
            if not isinstance(thing, dict):
                continue
            target = _consumable_topup_target(
                thing,
                minimum=minimum,
                herb_minimum=herb_minimum,
                kibble_minimum=kibble_minimum,
                godsbeard_minimum=godsbeard_minimum,
                scholarwort_minimum=scholarwort_minimum,
                is_pet_owner=bool(pet_owners) and character_guid in pet_owners,
                is_healer=bool(healers) and character_guid in healers,
            )
            if target is None:
                continue
            try:
                count = int(thing.get("_stackCount") or 0)
            except (TypeError, ValueError):
                count = 0
            if count < target:
                thing["_stackCount"] = int(target)
                updated_entries += 1
        break

    if not found_character:
        return data, False, 0
    if updated_entries == 0:
        return data, True, 0

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, updated_entries


def ensure_party_herb_tool_minimum(
    data: bytes,
    guids: list[str],
    *,
    minimum: int = 10,
    herb_minimum: int | None = None,
    kibble_minimum: int | None = None,
    godsbeard_minimum: int | None = None,
    scholarwort_minimum: int | None = None,
    pet_owners: Collection[str] | None = None,
    healers: Collection[str] | None = None,
) -> tuple[bytes, bool, int]:
    """Top up consumables for every party member listed in *guids*.

    Unlike repeatedly calling ``ensure_character_herb_tool_minimum`` (which
    decrypts/encrypts once per guid), this parses the GameRun once, mutates
    each character's Things in a single pass, and serializes once.

    *minimum* is the generic floor; *herb_minimum* / *kibble_minimum* /
    *godsbeard_minimum* / *scholarwort_minimum* are the optional specialised
    floors (herbs, a pet owner's kibble, a healer's godsbeard, Scholar's Wort
    — see ``_consumable_topup_target``).  *pet_owners* / *healers* are guid
    collections deciding who those conditional floors apply to.
    """
    if minimum < 0:
        raise ValueError("minimum must be >= 0")
    if not guids:
        return data, False, 0

    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, 0
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, 0

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False, 0

    guid_set = set(guids)
    total_updated = 0
    any_found = False
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        guid = entity.get("Guid")
        if guid not in guid_set:
            continue
        any_found = True
        comps = entity.get("Components") or {}
        cc = comps.get("CharacterComponent") or {}
        things = cc.get("Things") or []
        if not isinstance(things, list):
            continue
        is_pet_owner = bool(pet_owners) and guid in pet_owners
        is_healer = bool(healers) and guid in healers
        for thing in things:
            if not isinstance(thing, dict):
                continue
            target = _consumable_topup_target(
                thing,
                minimum=minimum,
                herb_minimum=herb_minimum,
                kibble_minimum=kibble_minimum,
                godsbeard_minimum=godsbeard_minimum,
                scholarwort_minimum=scholarwort_minimum,
                is_pet_owner=is_pet_owner,
                is_healer=is_healer,
            )
            if target is None:
                continue
            try:
                count = int(thing.get("_stackCount") or 0)
            except (TypeError, ValueError):
                count = 0
            if count < target:
                thing["_stackCount"] = int(target)
                total_updated += 1

    if not any_found:
        return data, False, 0
    if total_updated == 0:
        return data, True, 0

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, total_updated


def ensure_party_food_minimum(
    data: bytes,
    guids: list[str],
    *,
    minimum: int = 10,
    configs: tuple[str, ...] = ("SNICKERDOODLE_BASIC_01", "HOTDOG_BASIC_01"),
) -> tuple[bytes, bool, int]:
    """Top up the party's snack stacks (snickerdoodles / hotdogs) to *minimum*.

    Single-pass over the run for all *guids* (like
    ``ensure_party_herb_tool_minimum``).  Only existing stacks are raised;
    characters with none are left alone.
    """
    if minimum < 0:
        raise ValueError("minimum must be >= 0")
    if not guids:
        return data, False, 0

    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, 0
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, 0
    if not isinstance(run, dict):
        return data, False, 0

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False, 0

    config_set = {str(c).upper() for c in configs}
    guid_set = set(guids)
    total_updated = 0
    any_found = False
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        guid = entity.get("Guid")
        if guid not in guid_set:
            continue
        any_found = True
        comps = entity.get("Components") or {}
        cc = comps.get("CharacterComponent") or {}
        things = cc.get("Things") or []
        if not isinstance(things, list):
            continue
        for thing in things:
            if not isinstance(thing, dict):
                continue
            if str(thing.get("ConfigName") or "").upper() not in config_set:
                continue
            try:
                count = int(thing.get("_stackCount") or 0)
            except (TypeError, ValueError):
                count = 0
            if count < minimum:
                thing["_stackCount"] = int(minimum)
                total_updated += 1

    if not any_found:
        return data, False, 0
    if total_updated == 0:
        return data, True, 0

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, total_updated


CONSUMABLE_TOKENS = ("HERB", "DRINK", "TOOL", "SCROLL", "SAFETYSTONE", "ORB", "CANDY", "MISC_INK")

# Party top-up policy (GUI "Top up consumables"): herbs reach 15, a pet owner's
# kibble reaches 50, and a healer's godsbeard reaches 50.  Everything else
# consumable tops up to the generic ``minimum``.
GODSBEARD_CONFIG = "HERB_GODSBEARD_01"
KIBBLE_CONFIG = "TOOL_KIBBLE_01"
# Scholar's Wort is a herb, but not a potion: its only ability is
# BASIC_XP_ADD_01 ("Use this herb to gain {0} XP") and its config Value is 10,
# so it gets its own floor instead of the generic herb one.
SCHOLARWORT_CONFIG = "HERB_SCHOLARWORT_01"
HERB_STACK_MINIMUM = 15
KIBBLE_STACK_MINIMUM = 50
GODSBEARD_STACK_MINIMUM = 50
SCHOLARWORT_STACK_MINIMUM = 10


def _consumable_topup_target(
    thing: dict[str, Any],
    *,
    minimum: int,
    herb_minimum: int | None = None,
    kibble_minimum: int | None = None,
    godsbeard_minimum: int | None = None,
    scholarwort_minimum: int | None = None,
    is_pet_owner: bool = False,
    is_healer: bool = False,
) -> int | None:
    """Target stack count for a consumable *thing*, or ``None`` to skip it.

    ``minimum`` is the generic floor for any supported consumable.  The
    specialised floors are opt-in (skipped when ``None``): ``herb_minimum``
    raises every herb, ``scholarwort_minimum`` overrides that one XP herb,
    ``kibble_minimum`` applies only to pet owners, and ``godsbeard_minimum``
    only to healers.
    """
    config = str(thing.get("ConfigName") or "").upper()
    thing_type = str(thing.get("Type") or "").upper()
    is_supported = (
        "HERB" in config
        or "TOOL" in config
        or "DRINK" in config
        or "SCROLL" in config
        or "SAFETYSTONE" in config
        or "THROW" in config
        or "ORB" in config
        or "CANDY" in config
        or "MISC_INK" in config
        or thing_type in {"HERB", "TOOL"}
    )
    if not is_supported:
        return None
    if kibble_minimum is not None and config == KIBBLE_CONFIG:
        # Kibble only matters for characters that actually own a pet.
        return kibble_minimum if is_pet_owner else None
    if godsbeard_minimum is not None and config == GODSBEARD_CONFIG and is_healer:
        return godsbeard_minimum
    if scholarwort_minimum is not None and config == SCHOLARWORT_CONFIG:
        # Checked before the herb rule: it is a herb, but with its own floor.
        return scholarwort_minimum
    if herb_minimum is not None and ("HERB" in config or thing_type == "HERB"):
        return herb_minimum
    return minimum


def _is_consumable(thing: dict[str, Any]) -> bool:
    """True for non-equipment, non-currency, non-XP consumables (herbs, drinks, tools, scrolls, safetystones, orbs, candy, MISC_INK)."""
    config = str(thing.get("ConfigName") or "").upper()
    thing_type = str(thing.get("Type") or "").upper()
    if thing_type in {"EQUIPMENT", "PASSIVE"} or config == "CURRENCY_ADVENTURE":
        return False
    return any(token in config for token in CONSUMABLE_TOKENS) or thing_type in {"HERB", "TOOL"}


def _run_party_characters(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Party characters of a GameRun (player entities or companions).

    Includes players, companions, and mercenary followers from PlayerFollowers.
    Returns empty list for non-dict runs (fail-closed for malformed data).
    """
    if not isinstance(run, dict):
        return []
    entities = run.get("Entities")
    if not isinstance(entities, list):
        return []
    followers = run.get("PlayerFollowers")
    follower_guids: set[str] = set()
    if isinstance(followers, dict):
        for info in followers.values():
            if isinstance(info, dict):
                # Match viewmodel.py: primary key is FollowerID, fallback to CharacterGuid/Guid
                guid = info.get("FollowerID") or info.get("CharacterGuid") or info.get("Guid")
                if isinstance(guid, str) and guid:
                    follower_guids.add(guid)
    party: list[dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        comps = entity.get("Components")
        if not isinstance(comps, dict):
            continue
        cc = comps.get("CharacterComponent")
        if not isinstance(cc, dict) or not isinstance(cc.get("Things"), list):
            continue
        has_player = isinstance(comps.get("PlayerComponent"), dict)
        ctype = str(cc.get("CharacterType") or "")
        is_follower = entity.get("Guid") in follower_guids
        if has_player or is_follower or ctype in {"COMPANION", "MERCENARY"}:
            party.append(entity)
    return party


def carry_over_consumables(target: bytes, source: bytes) -> tuple[bytes, bool, int]:
    """Carry consumables from *source* (a previous act's GameRun) onto *target*'s party.

    Sums each consumable (herb/drink/tool/scroll/safetystone) party-wide in the
    source save, then adds the total onto the target party's matching stack —
    preferring the same character class as the dominant holder, then any member
    that already holds the item, then the first party member.  Equipment, gold
    (``CURRENCY_ADVENTURE``) and XP (``PASSIVE``) are never copied.

    Returns ``(new_target_bytes, ok, updated_entries)`` where ``ok`` means both
    inputs were GameRun saves with a non-empty party.
    """
    plain = decrypt_ftk2_bytes(target)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return target, False, 0
    target_summary, target_body, joiner = parts
    try:
        target_run = json.loads(target_body)
    except json.JSONDecodeError:
        return target, False, 0

    source_plain = decrypt_ftk2_bytes(source)
    source_parts = _split_gamerun_plain(source_plain)
    if source_parts is None:
        return target, False, 0
    try:
        source_run = json.loads(source_parts[1])
    except json.JSONDecodeError:
        return target, False, 0

    source_party = _run_party_characters(source_run)
    if not source_party:
        return target, False, 0

    # Party-wide pool: ConfigName -> (holder class, count, source prototype).
    per_config: dict[str, list[tuple[str, int, dict[str, Any]]]] = {}
    for entity in source_party:
        cc = (entity.get("Components") or {}).get("CharacterComponent") or {}
        char_class = str(cc.get("ConfigName") or "")
        for thing in cc.get("Things") or []:
            if not isinstance(thing, dict) or not _is_consumable(thing):
                continue
            config = str(thing.get("ConfigName") or "")
            if not config:
                continue
            try:
                count = int(thing.get("_stackCount") or 0)
            except (TypeError, ValueError):
                count = 0
            per_config.setdefault(config, []).append((char_class, count, thing))

    pool = {
        config: (
            sum(n for _, n, _ in holders),
            max(holders, key=lambda h: h[1])[0],
            max(holders, key=lambda h: h[1])[2],
        )
        for config, holders in per_config.items()
    }

    target_party = _run_party_characters(target_run)
    if not target_party:
        return target, False, 0

    if not pool:
        return target, True, 0

    updated_entries = 0
    for config, (amount, dominant_class, prototype) in sorted(pool.items()):
        if amount <= 0:
            continue
        # Recipient: same class as dominant holder, else anyone holding it, else first member.
        recipient: dict[str, Any] | None = None
        for entity in target_party:
            cc = (entity.get("Components") or {}).get("CharacterComponent") or {}
            if str(cc.get("ConfigName") or "") == dominant_class:
                recipient = entity
                break
        if recipient is None:
            for entity in target_party:
                cc = (entity.get("Components") or {}).get("CharacterComponent") or {}
                if any(
                    isinstance(t, dict) and t.get("ConfigName") == config
                    for t in cc.get("Things") or []
                ):
                    recipient = entity
                    break
        if recipient is None:
            recipient = target_party[0]

        cc = (recipient.get("Components") or {}).setdefault("CharacterComponent", {})
        things = cc.setdefault("Things", [])
        if not isinstance(things, list):
            return target, False, 0
        existing = None
        for thing in things:
            if isinstance(thing, dict) and thing.get("ConfigName") == config:
                existing = thing
                break
        if existing is not None:
            try:
                existing["_stackCount"] = int(existing.get("_stackCount") or 0) + amount
            except (TypeError, ValueError):
                existing["_stackCount"] = amount
        else:
            things.append(
                {
                    "Id": str(uuid.uuid4()),
                    "ConfigName": config,
                    "Type": str(prototype.get("Type") or "ITEM"),
                    "_stackCount": amount,
                    "Expansion": str(prototype.get("Expansion") or "BASE"),
                }
            )
        updated_entries += 1

    new_body = _dump_json_matching_newlines(target_run, target_body)
    new_plain = f"//**{target_summary}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, updated_entries


def set_local_stat(data: bytes, stat_name: str, value: int) -> tuple[bytes, bool]:
    """Convenience wrapper for ``LocalStats`` integer edits."""
    return edit_field(data, f"LocalStats.{stat_name}", str(int(value)))


# Default appearance used when building a fresh mercenary. Matches the exact
# AvatarComponent the game serializes for a base mercenary (verified from a
# real GameRun); copy-compatible with players that carry extra fields such as
# "BodyType".
_DEFAULT_MERC_AVATAR: dict[str, Any] = {
    "EquipmentSlotVisibility": {},
    "PrimaryColor": "3C3A39FF",
    "SecondaryColor": "425454FF",
    "SkinColor": "A86957FF",
    "HairColor": "73513BFF",
    "SkinColorOverride": "",
    "OverrideSkinMaterial": False,
    "OverrideSkinMaterialIndex": 0,
    "IsLefty": False,
    "ScaleMultiplier": 1,
    "Scale": {"X": 0.987300098, "Y": 0.987300098, "Z": 0.987300098},
    "Position": {"X": 0, "Y": 0, "Z": 0},
    "SkinDirty": False,
    "EquipmentDirty": False,
    "StatusDirty": True,
    "PortraitDirty": True,
}


def _follower_avatar(host_avatar: Any) -> dict[str, Any]:
    """Avatar shape for a follower entity we inject into a run.

    Game-created followers never carry ``BodyType`` in their serialized
    AvatarComponent: the game reads ``CharacterComponent.ConfigName`` in its
    plain form and resolves tier records via ``Index.dCharacter``.  If a
    follower DID carry ``BodyType`` (players do), ``CharacterVisualHelper``
    rewrites the config as ``{ConfigName}_{BodyType}`` and then looks that up
    in ``Configs.Characters`` (Characters.json), which has no gender-suffixed
    keys -- a ``KeyNotFoundException`` on load (the ``..._02_M`` / ``..._02_F``
    crashes).  A plain config name with no ``BodyType`` takes the fallback path
    that never throws.

    Copies the palette/flags the host carries for the exact keys the game
    serializes for a base follower, but never ``BodyType`` or player-only
    fields.
    """
    base = dict(_DEFAULT_MERC_AVATAR)
    if isinstance(host_avatar, dict):
        for key in _DEFAULT_MERC_AVATAR:
            if key in host_avatar:
                base[key] = host_avatar[key]
    return base


def _occupied_tiles(
    entities: list[Any],
    *,
    exclude_guids: Collection[str] = (),
) -> set[tuple[int, int]]:
    """Venue tiles already claimed by entities in a run's ``Entities`` list.

    Only 1x1 venues are considered (every player and follower in a real save is
    one), so a multi-tile venue is skipped rather than half-counted.
    """
    skip = {str(g) for g in exclude_guids}
    taken: set[tuple[int, int]] = set()
    for entity in entities:
        if not isinstance(entity, dict) or str(entity.get("Guid")) in skip:
            continue
        venue = (entity.get("Components") or {}).get("VenueComponent")
        if not isinstance(venue, dict):
            continue
        size = venue.get("TileSize")
        if isinstance(size, dict) and (size.get("Item1") or 1) != 1:
            continue
        pos = venue.get("TilePosition")
        if not isinstance(pos, dict):
            continue
        try:
            taken.add((int(pos.get("Item1") or 0), int(pos.get("Item2") or 0)))
        except (TypeError, ValueError):
            continue
    return taken


def _follower_placement(
    host_comps: dict[str, Any],
    taken: Collection[tuple[int, int]] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adventure/venue components for a follower injected next to *host_comps*.

    A follower is only drawn if it carries both, and the game always writes
    both for a bound one: ``AdventureComponent`` repeats the host's hex and
    map verbatim, and ``VenueComponent`` is a 1x1 venue on a tile *beside* the
    host's (observed ``{Item1: 3, Item2: n}`` -> ``{Item1: 4, Item2: n}``).  A
    follower entity with neither component — which is what an unbound recruit
    template looks like in ``Entities`` — is never placed, so the game keeps it
    invisible: no hex, no tile, nothing on screen.

    The hex is copied as-is (that is what the game does; the follower's world
    position is driven by its venue tile).  The venue tile starts beside the
    host and walks outward until it lands on a tile not in *taken*, so a party
    where several heroes each have a follower does not stack them all on one
    tile; the host's own tile is the last resort.  Falls back to the origin for
    a host with no position components, which is still better than writing
    none.
    """
    host_adventure = host_comps.get("AdventureComponent")
    host_venue = host_comps.get("VenueComponent")
    adventure: dict[str, Any] = (
        dict(host_adventure)
        if isinstance(host_adventure, dict)
        else {"HexPosition": {"Item1": 0, "Item2": 0}, "MapID": ""}
    )
    if not isinstance(host_venue, dict):
        return adventure, {
            "TilePosition": {"Item1": 1, "Item2": 0},
            "TileSize": {"Item1": 1, "Item2": 1},
            "OccupiedTiles": [{"Item1": 1, "Item2": 0}],
        }

    venue = copy.deepcopy(host_venue)
    pos = venue.get("TilePosition")
    if not isinstance(pos, dict):
        return adventure, venue
    try:
        col = int(pos.get("Item1") or 0)
        row = int(pos.get("Item2") or 0)
    except (TypeError, ValueError):
        return adventure, venue
    occupied = {(int(a), int(b)) for a, b in taken}
    chosen = (col, row)
    for delta_col, delta_row in ((1, 0), (-1, 0), (0, 1), (0, -1), (0, 0)):
        candidate = (col + delta_col, row + delta_row)
        if candidate not in occupied or candidate == (col, row):
            chosen = candidate
            break
    pos["Item1"], pos["Item2"] = chosen
    venue["TilePosition"] = pos
    if "OccupiedTiles" in venue:
        venue["OccupiedTiles"] = [{"Item1": chosen[0], "Item2": chosen[1]}]
    return adventure, venue


def _follower_slot_taken(run: dict[str, Any], host_player_guid: str) -> bool:
    """True when *host_player_guid* already has a follower bound to it.

    ``PlayerFollowers`` is a map keyed by player GUID, so a host holds at most
    one follower.  Recruiting without this guard silently overwrites the
    binding and leaves the previous follower entity orphaned in ``Entities``
    (still spendable/AI-driven, but owned by nobody), so both ``add_pet`` and
    ``add_mercenary`` fail closed instead.  An entry with a missing/empty
    ``FollowerID`` is not a binding, so it does not block a recruit.
    """
    followers = run.get("PlayerFollowers")
    if not isinstance(followers, dict):
        return False
    state = followers.get(host_player_guid)
    if not isinstance(state, dict):
        return False
    return bool(state.get("FollowerID"))


def add_mercenary(
    data: bytes,
    host_player_guid: str,
    spec: dict[str, Any],
) -> tuple[bytes, bool, str]:
    """Add a mercenary follower to a run, bound to the given player.

    ``spec`` describes what to build, e.g. from ``viewmodel.mercenary_spec``:

    ``{"type_args": "MERC_GUN_01", "config_name": "MERC_GUN_BASIC_06",
    "contract_rounds": 6, "start_health": 120, "start_focus": 0,
    "start_things": ["GUN_MILITIA_TINY_03"]}``

    Produces one new placeholder entity (CharacterComponent + AIComponent +
    game-shaped avatar + adventure/venue copied from the host so it spawns
    beside the party) and registers it in ``PlayerFollowers`` for the host
    player.

    Fail-closed: returns ``(data, False, "")`` on non-GameRun data, invalid
    structure, an unknown or non-player host, duplicate host GUIDs, an empty
    spec, or a host that already has a follower bound in ``PlayerFollowers``
    (a host holds one at a time; remove the current one first, otherwise the
    old follower would be orphaned).
    """
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, ""
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, ""
    if (
        not isinstance(run, dict)
        or not isinstance(spec, dict)
        or not host_player_guid
        or not spec.get("config_name")
    ):
        return data, False, ""

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False, ""
    for e in entities:
        if not isinstance(e, dict):
            return data, False, ""

    hosts = [e for e in entities if e.get("Guid") == host_player_guid]
    if len(hosts) != 1:
        return data, False, ""
    host = hosts[0]
    host_comps = host.get("Components")
    if not isinstance(host_comps, dict) or not isinstance(
        host_comps.get("PlayerComponent"), dict
    ):
        return data, False, ""
    if _follower_slot_taken(run, host_player_guid):
        return data, False, ""

    new_guid = str(uuid.uuid4())
    thing_ids: list[str] = []
    things: list[dict[str, Any]] = []
    for config in spec.get("start_things") or []:
        if not isinstance(config, str) or not config:
            continue
        thing_id = str(uuid.uuid4())
        thing_ids.append(thing_id)
        things.append(
            {
                "Id": thing_id,
                "ConfigName": config,
                "Type": "EQUIPMENT",
                "_stackCount": 1,
                "Expansion": "BASE",
            }
        )

    equipped: dict[str, str] = {
        "MAIN_HAND": thing_ids[0] if thing_ids else "",
        "OFF_HAND": "",
        "HELMET": "",
        "ARMOR": "",
        "GLOVES": "",
        "BOOTS": "",
        "TRINKET": "",
        "BACKPACK": "",
        "PIPE": "",
    }

    character_component: dict[str, Any] = {
        "ConfigName": spec["config_name"],
        "CurrentHealth": int(spec.get("start_health") or 0),
        "CurrentFocus": int(spec.get("start_focus") or 0),
        "ExtraLives": 0,
        "NecroLives": 0,
        "ExtraLevel": 0,
        "CharacterType": "MERCENARY",
        "TypeArgs": str(spec.get("type_args") or ""),
        "GroupIndex": 0,
        "Things": things,
        "Equipped": equipped,
        "SkinEquipped": {},
        "BaseStatModifiers": {},
        "State": "DEFAULT",
    }

    host_avatar = host_comps.get("AvatarComponent")
    avatar = _follower_avatar(host_avatar)
    adventure, venue = _follower_placement(
        host_comps, _occupied_tiles(entities, exclude_guids=(host_player_guid,))
    )

    entity: dict[str, Any] = {
        "Guid": new_guid,
        "Components": {
            "CharacterComponent": character_component,
            "AIComponent": {},
            "AvatarComponent": avatar,
            "AdventureComponent": adventure,
            "VenueComponent": venue,
        },
    }
    entities.append(entity)

    followers = run.get("PlayerFollowers")
    if not isinstance(followers, dict):
        followers = {}
        run["PlayerFollowers"] = followers
    followers[host_player_guid] = {
        "FollowerID": new_guid,
        "RoundsToExpire": int(spec.get("contract_rounds") or 0),
    }

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, new_guid


def swap_character_class(
    data: bytes,
    character_guid: str,
    new_config: str,
) -> tuple[bytes, bool]:
    """Change a run character's class by updating ``CharacterComponent.ConfigName``.

    The chosen config must be a playable class config (see
    ``viewmodel.playable_class_names``) for a meaningful result; the game
    derives stats/starting gear from ``Characters.json`` on load. NPCs without
    a CharacterComponent are unchanged.

    Fail-closed: returns ``(data, False)`` on non-GameRun data, invalid
    structure, or an unknown/duplicate character GUID.
    """
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False
    if not isinstance(run, dict) or not character_guid or not new_config:
        return data, False

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False
    for e in entities:
        if not isinstance(e, dict):
            return data, False

    matching = [e for e in entities if e.get("Guid") == character_guid]
    if len(matching) != 1:
        return data, False
    entity = matching[0]
    comps = entity.get("Components")
    if not isinstance(comps, dict):
        return data, False
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return data, False
    cc["ConfigName"] = new_config

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True


def add_pet(
    data: bytes,
    host_player_guid: str,
    spec: dict[str, Any],
) -> tuple[bytes, bool, str]:
    """Add a companion pet to a run, bound to the given player.

    ``spec`` describes what to build, e.g. from ``viewmodel.companion_spec``:

    ``{"type_args": "COMPANION_RAT_01", "config_name": "COMPANION_RAT_BASIC_06",
    "contract_rounds": 0, "start_health": 95, "start_focus": 1,
    "start_things": []}``

    Produces one new placeholder entity (CharacterComponent + AIComponent +
    game-shaped avatar + adventure/venue copied from the host so it spawns
    beside the party) and registers it in ``PlayerFollowers`` for the host
    player.  The pet is given ``KIBBLE_CONFIG`` x50 and an XP counter, matching
    how the game stores its own companions.

    The adventure/venue pair is not optional: the game only draws a follower
    that has both, so a pet written without them is bound and alive in the
    save but invisible on the map.  See ``_follower_placement``.

    Fail-closed: returns ``(data, False, "")`` on non-GameRun data, invalid
    structure, an unknown or non-player host, duplicate host GUIDs, an empty
    spec, or a host that already has a follower bound in ``PlayerFollowers``
    (a host holds one at a time; remove the current one first, otherwise the
    old follower would be orphaned).
    """
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, ""
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, ""
    if (
        not isinstance(run, dict)
        or not isinstance(spec, dict)
        or not host_player_guid
        or not spec.get("config_name")
    ):
        return data, False, ""

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False, ""
    for e in entities:
        if not isinstance(e, dict):
            return data, False, ""

    hosts = [e for e in entities if e.get("Guid") == host_player_guid]
    if len(hosts) != 1:
        return data, False, ""
    host = hosts[0]
    host_comps = host.get("Components")
    if not isinstance(host_comps, dict) or not isinstance(
        host_comps.get("PlayerComponent"), dict
    ):
        return data, False, ""

    if _follower_slot_taken(run, host_player_guid):
        return data, False, ""

    new_guid = str(uuid.uuid4())
    things: list[dict[str, Any]] = [
        {
            "Id": str(uuid.uuid4()),
            "ConfigName": "XP",
            "Type": "PASSIVE",
            "_stackCount": 0,
            "Expansion": "BASE",
        },
        {
            "Id": str(uuid.uuid4()),
            "ConfigName": KIBBLE_CONFIG,
            "Type": "ITEM",
            "_stackCount": KIBBLE_STACK_MINIMUM,
            "Expansion": "BASE",
        },
    ]

    character_component: dict[str, Any] = {
        "ConfigName": spec["config_name"],
        "CurrentHealth": int(spec.get("start_health") or 0),
        "CurrentFocus": int(spec.get("start_focus") or 1),
        "ExtraLives": 0,
        "NecroLives": 0,
        "ExtraLevel": 0,
        "CharacterType": "COMPANION",
        "TypeArgs": str(spec.get("type_args") or ""),
        "GroupIndex": 1,
        "Things": things,
        "Equipped": {
            "MAIN_HAND": "",
            "OFF_HAND": "",
            "HELMET": "",
            "ARMOR": "",
            "GLOVES": "",
            "BOOTS": "",
            "TRINKET": "",
            "BACKPACK": "",
            "PIPE": "",
        },
        "SkinEquipped": {},
        "BaseStatModifiers": {},
        "State": "DEFAULT",
    }

    host_avatar = host_comps.get("AvatarComponent")
    avatar = _follower_avatar(host_avatar)
    adventure, venue = _follower_placement(
        host_comps, _occupied_tiles(entities, exclude_guids=(host_player_guid,))
    )

    entity: dict[str, Any] = {
        "Guid": new_guid,
        "Components": {
            "CharacterComponent": character_component,
            "AIComponent": {},
            "AvatarComponent": avatar,
            "AdventureComponent": adventure,
            "VenueComponent": venue,
        },
    }
    entities.append(entity)

    followers = run.get("PlayerFollowers")
    if not isinstance(followers, dict):
        followers = {}
        run["PlayerFollowers"] = followers
    followers[host_player_guid] = {
        "FollowerID": new_guid,
        "RoundsToExpire": int(spec.get("contract_rounds") or 0),
    }

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, new_guid


# The Dark Carnival's "Evil Reflection": a bound COMPANION that mirrors its
# host.  Marked by TypeArgs COMPANION_REFLECTION and Properties
# ["EVIL", "REFLECTION"], carrying the *host's own* class config.
REFLECTION_TYPE_ARGS = "COMPANION_REFLECTION"
# The in-run wallet counter (viewmodel defines the same constant for display).
_WALLET_CONFIG = "CURRENCY_ADVENTURE"
REFLECTION_PROPERTIES = ["EVIL", "REFLECTION"]
# Real reflections are bound with RoundsToExpire -1 (permanent), unlike a
# contract follower which counts down.
REFLECTION_ROUNDS_TO_EXPIRE = -1


def add_evil_reflection(
    data: bytes,
    host_player_guid: str,
    *,
    replace: bool = False,
    copy_inventory: bool = True,
    health_ratio: float = 0.75,
    focus_cap: int | None = 3,
) -> tuple[bytes, bool, str]:
    """Create a Dark Carnival Evil Reflection of *host_player_guid*.

    A reflection is a bound ``COMPANION`` that mirrors its host: the host's own
    class ``ConfigName``, ``TypeArgs`` ``COMPANION_REFLECTION``,
    ``Properties`` ``["EVIL", "REFLECTION"]``, ``DisplayName`` "Evil <host>",
    the host's health/focus, and its own map placement on a free tile beside
    the host (see ``_follower_placement``).  A real one carries a full class
    loadout, which is what *copy_inventory* reproduces by cloning the host's
    ``Things`` with fresh ``Id``s.

    The wallet and XP stacks are never cloned: ``CURRENCY_*`` and ``XP`` are
    per-character counters, and copying them would duplicate the host's gold
    and XP into a second body.  They are recreated empty instead, so the game
    still has the counters it expects.

    Three details are taken from the reflections in a real save rather than
    from the host, because copying the host's would be wrong:

    * ``Equipped`` is remapped onto the cloned stacks' new ``Id``s.  The game
      resolves a slot by thing id, so a copied map would leave every equipped
      slot dangling at gear the reflection does not have; the real ones have no
      dangling slot.  A slot whose item was not mirrored is emptied.
    * ``BaseStatModifiers`` and ``SkinEquipped`` are reset to ``{}`` — the
      real reflections carry no stat or skin overrides even when the host has
      some.
    * the reflection is *weaker* than its host: both reference reflections sit
      at 72-75% of the host's health with focus 3, so *health_ratio* scales
      health and *focus_cap* caps focus (pass ``None`` to keep the host's).

    Fail-closed: returns ``(data, False, "")`` on non-GameRun data, invalid
    structure, an unknown/non-player/duplicated host, or a host that already
    has a follower and *replace* unset.
    """
    if not host_player_guid:
        return data, False, ""
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, ""
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, ""
    if not isinstance(run, dict):
        return data, False, ""

    entities = run.get("Entities")
    if not isinstance(entities, list):
        return data, False, ""
    for e in entities:
        if not isinstance(e, dict):
            return data, False, ""

    hosts = [e for e in entities if e.get("Guid") == host_player_guid]
    if len(hosts) != 1:
        return data, False, ""
    host = hosts[0]
    host_comps = host.get("Components")
    if not isinstance(host_comps, dict) or not isinstance(
        host_comps.get("PlayerComponent"), dict
    ):
        return data, False, ""
    host_cc = host_comps.get("CharacterComponent")
    if not isinstance(host_cc, dict) or not host_cc.get("ConfigName"):
        return data, False, ""
    if _follower_slot_taken(run, host_player_guid) and not replace:
        return data, False, ""

    host_name = str(host_cc.get("DisplayName") or "").strip()
    config = str(host_cc.get("ConfigName") or "")

    things: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}
    if copy_inventory:
        for thing in host_cc.get("Things") or []:
            if not isinstance(thing, dict):
                continue
            name = str(thing.get("ConfigName") or "").upper()
            if name.startswith("CURRENCY_") or name == "XP":
                continue  # per-character counters, never mirrored
            clone = copy.deepcopy(thing)
            old_id = thing.get("Id")
            clone["Id"] = str(uuid.uuid4())
            if isinstance(old_id, str) and old_id:
                id_map[old_id] = clone["Id"]
            things.append(clone)
    # Fresh empty counters: the game reads these, and mirroring the host's
    # values would hand out a second wallet's worth of gold and XP.
    things.append(
        {
            "Id": str(uuid.uuid4()),
            "ConfigName": "XP",
            "Type": "PASSIVE",
            "_stackCount": 0,
            "Expansion": "BASE",
        }
    )
    things.append(
        {
            "Id": str(uuid.uuid4()),
            "ConfigName": _WALLET_CONFIG,
            "Type": "ITEM",
            "_stackCount": 0,
            "Expansion": "BASE",
        }
    )

    character_component: dict[str, Any] = copy.deepcopy(host_cc)
    character_component["DisplayName"] = (
        f"Evil {host_name}" if host_name else f"Evil {config}"
    )
    character_component["TypeArgs"] = REFLECTION_TYPE_ARGS
    character_component["CharacterType"] = "COMPANION"
    character_component["Properties"] = list(REFLECTION_PROPERTIES)
    character_component["Things"] = things
    # Point every slot at the mirrored copy of the same item, and empty the
    # slots whose item was not mirrored: a slot id the entity does not own is
    # exactly what the real reflections never have.
    equipped = host_cc.get("Equipped")
    if isinstance(equipped, dict):
        character_component["Equipped"] = {
            slot: id_map.get(str(thing_id) or "", "")
            for slot, thing_id in equipped.items()
        }
    character_component["BaseStatModifiers"] = {}
    character_component["SkinEquipped"] = {}
    # A reflection is weaker than the hero it mirrors.
    try:
        host_health = int(host_cc.get("CurrentHealth") or 0)
    except (TypeError, ValueError):
        host_health = 0
    if host_health > 0 and health_ratio > 0:
        character_component["CurrentHealth"] = max(1, int(host_health * health_ratio))
    if focus_cap is not None:
        try:
            host_focus = int(host_cc.get("CurrentFocus") or 0)
        except (TypeError, ValueError):
            host_focus = 0
        character_component["CurrentFocus"] = min(host_focus, int(focus_cap))
    # A reflection is not a player: drop anything player-shaped.
    character_component.pop("IsPlayer", None)

    avatar = _follower_avatar(host_comps.get("AvatarComponent"))
    adventure, venue = _follower_placement(
        host_comps, _occupied_tiles(entities, exclude_guids=(host_player_guid,))
    )

    new_guid = str(uuid.uuid4())
    entities.append(
        {
            "Guid": new_guid,
            "Components": {
                "CharacterComponent": character_component,
                "AIComponent": {},
                "AvatarComponent": avatar,
                "AdventureComponent": adventure,
                "VenueComponent": venue,
            },
        }
    )

    followers = run.get("PlayerFollowers")
    if not isinstance(followers, dict):
        followers = {}
        run["PlayerFollowers"] = followers
    followers[host_player_guid] = {
        "FollowerID": new_guid,
        "RoundsToExpire": REFLECTION_ROUNDS_TO_EXPIRE,
    }

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, new_guid


def remove_follower(data: bytes, follower_guid: str) -> tuple[bytes, bool]:
    """Remove a mercenary/companion follower entity from a run.

    Deletes the entity and every ``PlayerFollowers`` entry whose ``FollowerID``
    points at it, so the party slot is freed and a different follower can be
    added.  A real save references a follower in exactly those two places (the
    entity itself and the host's ``PlayerFollowers`` entry).

    Fail-closed: returns ``(data, False)`` on non-GameRun data, invalid
    structure, a missing/duplicate GUID, or a character that is not a removable
    follower (a player-controlled entity, or one that is neither typed
    ``MERCENARY``/``COMPANION`` nor bound in ``PlayerFollowers``).  The one
    exception is a *dangling* binding -- a ``PlayerFollowers`` entry pointing
    at a GUID with no entity -- which is cleared on its own so the slot can be
    reused instead of being stuck forever.
    """
    if not follower_guid:
        return data, False
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False
    if not isinstance(run, dict):
        return data, False

    entities = run.get("Entities")
    if not isinstance(entities, list) or not all(
        isinstance(e, dict) for e in entities
    ):
        return data, False

    followers = run.get("PlayerFollowers")
    hosts: list[str] = []
    if isinstance(followers, dict):
        hosts = [
            host
            for host, state in followers.items()
            if isinstance(state, dict) and state.get("FollowerID") == follower_guid
        ]

    matches = [e for e in entities if e.get("Guid") == follower_guid]
    if not matches and hosts:
        # Dangling binding: the follower entity is already gone (a save edited
        # by hand, or one the game pruned).  Drop the host's reference so the
        # slot becomes recruitable again instead of failing closed forever.
        for host in hosts:
            del followers[host]  # type: ignore[index]
        new_body = _dump_json_matching_newlines(run, body_text)
        new_plain = f"//**{summary_text}**//{joiner}{new_body}"
        return encrypt_ftk2_text(new_plain), True
    if len(matches) != 1:
        return data, False
    entity = matches[0]
    comps = entity.get("Components")
    if not isinstance(comps, dict):
        return data, False
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return data, False
    if isinstance(comps.get("PlayerComponent"), dict):
        return data, False

    if cc.get("CharacterType") not in ("MERCENARY", "COMPANION") and not hosts:
        return data, False

    entities.remove(entity)
    if isinstance(followers, dict):
        for host in hosts:
            del followers[host]

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True


def repair_follower_placement(data: bytes) -> tuple[bytes, bool, list[str]]:
    """Give every placement-less bound follower its host's map position.

    A follower entity with no ``AdventureComponent``/``VenueComponent`` is
    bound in ``PlayerFollowers`` and alive, but the game never places it, so
    it does not appear on screen.  Older versions of this editor wrote pet
    entities that way (the shape of an *unbound* recruit template, which the
    game also stores unplaced in ``Entities``), so a save edited by them can
    hold an invisible pet.  This back-fills the pair from the bound host, the
    same way ``add_pet``/``add_mercenary`` do now.

    Returns ``(data, True, repaired_guids)``; the guid list is empty when
    nothing needed fixing (the data comes back re-serialised either way, so
    compare the list rather than the bytes).  Fail-closed: returns
    ``(data, False, [])`` on non-GameRun data or invalid structure.  Followers
    that already carry placement are left untouched, so this is safe to run on
    a healthy save.
    """
    plain = decrypt_ftk2_bytes(data)
    parts = _split_gamerun_plain(plain)
    if parts is None:
        return data, False, []
    summary_text, body_text, joiner = parts
    try:
        run = json.loads(body_text)
    except json.JSONDecodeError:
        return data, False, []
    if not isinstance(run, dict):
        return data, False, []

    entities = run.get("Entities")
    followers = run.get("PlayerFollowers")
    if not isinstance(entities, list) or not all(
        isinstance(e, dict) for e in entities
    ):
        return data, False, []
    if not isinstance(followers, dict):
        return data, False, []

    by_guid: dict[str, dict[str, Any]] = {}
    for e in entities:
        guid = e.get("Guid")
        if isinstance(guid, str) and guid and guid not in by_guid:
            by_guid[guid] = e

    repaired: list[str] = []
    for host_guid, state in followers.items():
        if not isinstance(state, dict):
            continue
        follower_guid = state.get("FollowerID")
        host = by_guid.get(host_guid)
        follower = by_guid.get(str(follower_guid or ""))
        if host is None or follower is None or follower is host:
            continue
        comps = follower.get("Components")
        host_comps = host.get("Components")
        if not isinstance(comps, dict) or not isinstance(host_comps, dict):
            continue
        if "AdventureComponent" in comps and "VenueComponent" in comps:
            continue
        adventure, venue = _follower_placement(
            host_comps,
            _occupied_tiles(entities, exclude_guids=(host_guid, follower["Guid"])),
        )
        comps["AdventureComponent"] = adventure
        comps["VenueComponent"] = venue
        repaired.append(follower["Guid"])

    if not repaired:
        return data, True, []

    new_body = _dump_json_matching_newlines(run, body_text)
    new_plain = f"//**{summary_text}**//{joiner}{new_body}"
    return encrypt_ftk2_text(new_plain), True, repaired


def backup(path: Path | str) -> Path:
    """Copy the save file to a ``.bak`` file and return the backup path."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Save file not found: {src}")

    bak = src.with_suffix(".bak")
    counter = 1
    while bak.exists():
        bak = src.with_suffix(f".bak.{counter}")
        counter += 1

    shutil.copy2(src, bak)
    return bak


def find_save_file(custom_path: str | None = None) -> Path:
    """Locate the FTK2 ``User.ftk2`` file."""
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Save file not found at custom path: {p}")

    if USER_SAVE.exists():
        return USER_SAVE

    if FTK2_GAME_DIR.exists():
        candidate = FTK2_GAME_DIR / "User.ftk2"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Could not locate User.ftk2.  Searched {FTK2_GAME_DIR}.  "
        "Is the game installed under Steam?"
    )


def verify_save(data: bytes) -> dict[str, Any]:
    """Verify BOM + successful decrypt-to-JSON (for User saves)."""
    issues: list[str] = []

    if not data.startswith(FTK2_BOM):
        issues.append("Missing UTF-8 BOM prefix")

    if len(data) < 32:
        issues.append(f"File suspiciously small ({len(data)} bytes)")

    if len(data) > 100_000_000:
        issues.append(f"File suspiciously large ({len(data)} bytes)")

    plain = ""
    looks_json = False
    try:
        plain = decrypt_ftk2_bytes(data)
        stripped = plain.lstrip()
        looks_json = stripped.startswith("{") or stripped.startswith("//**")
        if not looks_json:
            issues.append("Decrypted payload does not look like JSON / GameRun summary")
        elif stripped.startswith("{"):
            json.loads(plain)
    except UnicodeDecodeError:
        issues.append("File is not valid UTF-8 after BOM")
    except json.JSONDecodeError as exc:
        issues.append(f"Decrypted JSON failed to parse: {exc}")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "file_size": len(data),
        "has_bom": data.startswith(FTK2_BOM),
        "decrypts_to_json": looks_json,
        "plaintext_prefix": plain[:60] if plain else "",
    }
