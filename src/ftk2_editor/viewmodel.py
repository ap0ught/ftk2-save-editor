"""Helpers for presenting FTK2 save contents in the CLI / GUI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ftk2_editor import FTK2_ASSETS_DIR, GAME_RUNS_DIR, USER_SAVE, parse_ftk2

CURRENCY_ADVENTURE = "CURRENCY_ADVENTURE"
CURRENCY_LORE = "CURRENCY_LORE"
THING_XP = "XP"


def thing_count(things: list[dict[str, Any]] | None, config_name: str) -> int | None:
    """Return ``_stackCount`` for the first Thing with ``ConfigName``."""
    if not things:
        return None
    for thing in things:
        if thing.get("ConfigName") == config_name:
            value = thing.get("_stackCount")
            return int(value) if value is not None else 0
    return None


def character_from_entity(entity: dict[str, Any]) -> dict[str, Any] | None:
    """Build a party-row dict from a run/user ``Entity``, or None if not a character."""
    comps = entity.get("Components") or {}
    cc = comps.get("CharacterComponent")
    if not isinstance(cc, dict):
        return None
    name = cc.get("DisplayName")
    config = cc.get("ConfigName")
    if not name and not config:
        return None

    things = cc.get("Things") or []
    equipped = cc.get("Equipped") or {}
    inventory = [
        {
            "config": t.get("ConfigName"),
            "type": t.get("Type"),
            "expansion": t.get("Expansion"),
            "count": t.get("_stackCount"),
            "id": t.get("Id"),
        }
        for t in things
        if isinstance(t, dict)
    ]
    inventory.sort(key=lambda row: (str(row.get("type") or ""), str(row.get("config") or "")))

    return {
        "guid": entity.get("Guid"),
        "name": name or config or "?",
        "class": config or "",
        "has_player_component": isinstance(comps.get("PlayerComponent"), dict),
        "character_type": cc.get("CharacterType"),
        "health": cc.get("CurrentHealth"),
        "focus": cc.get("CurrentFocus"),
        "gold": thing_count(things, CURRENCY_ADVENTURE),
        "xp": thing_count(things, THING_XP),
        "extra_lives": cc.get("ExtraLives"),
        "state": cc.get("State"),
        "map_id": (comps.get("AdventureComponent") or {}).get("MapID"),
        "equipped": dict(equipped) if isinstance(equipped, dict) else {},
        "inventory": inventory,
    }


def party_from_entities(
    entities: list[dict[str, Any]],
    *,
    guids: set[str] | None = None,
    standard_only: bool = True,
    player_only: bool = False,
    include_companions: bool = False,
) -> list[dict[str, Any]]:
    """Extract unique party-like characters from an Entities list."""
    rows: list[dict[str, Any]] = []
    seen_guids: set[str] = set()
    for entity in entities:
        if guids is not None and entity.get("Guid") not in guids:
            continue
        row = character_from_entity(entity)
        if row is None:
            continue
        if standard_only:
            ctype = row.get("character_type")
            # User snapshots may omit CharacterType; run players use STANDARD.
            if ctype is not None and ctype != "STANDARD":
                continue
        if player_only and not row.get("has_player_component"):
            ctype = str(row.get("character_type") or "")
            if not (include_companions and ctype == "COMPANION"):
                continue
        key = row["guid"]
        if key in seen_guids:
            continue
        seen_guids.add(key)
        rows.append(row)
    return rows


def party_from_user(user: dict[str, Any]) -> list[dict[str, Any]]:
    """Party snapshot from ``UserData.PartyCharacters`` (usually no wallet gold)."""
    entities = user.get("PartyCharacters") or []
    if not isinstance(entities, list):
        return []
    # Prefer matching guids so we keep order; allow missing CharacterType.
    rows: list[dict[str, Any]] = []
    for entity in entities:
        row = character_from_entity(entity)
        if row:
            rows.append(row)
    return rows


def party_from_run(
    run: dict[str, Any],
    *,
    preferred_guids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Party wallets from ``GameRunData.Entities``."""
    entities = run.get("Entities") or []
    if not isinstance(entities, list):
        return []
    if preferred_guids:
        guid_set = set(preferred_guids)
        matched = party_from_entities(
            entities,
            guids=guid_set,
            standard_only=False,
            player_only=True,
            include_companions=True,
        )
        if matched:
            # Preserve preferred order
            by_guid = {row["guid"]: row for row in matched}
            ordered = [by_guid[g] for g in preferred_guids if g in by_guid]
            return ordered or matched
    return party_from_entities(
        entities,
        standard_only=False,
        player_only=True,
        include_companions=True,
    )


def interesting_stats(stats: dict[str, Any] | None, *, limit: int = 80) -> list[tuple[str, Any]]:
    """Filter a stats dict to gold/lore/currency-ish keys, then fill remaining."""
    if not isinstance(stats, dict):
        return []
    tokens = ("GOLD", "LORE", "CURRENCY", "XP", "LEVEL", "KILL", "SPENT", "COLLECT")
    items = sorted(stats.items(), key=lambda item: str(item[0]))
    primary = [
        (k, v)
        for k, v in items
        if any(tok in str(k).upper() for tok in tokens)
    ]
    if len(primary) >= limit:
        return primary[:limit]
    primary_keys = {k for k, _ in primary}
    rest = [(k, v) for k, v in items if k not in primary_keys]
    return primary + rest[: max(0, limit - len(primary))]


def replacement_item_configs(
    catalog: list[dict[str, str]],
    selected: dict[str, Any],
    *,
    same_type: bool,
) -> list[str]:
    """Return replacement configs, optionally matching Type and ConfigName family."""
    current = str(selected.get("config") or "")
    wanted_type = selected.get("type")
    wanted_family = current.partition("_")[0]
    configs = {
        str(item["config"])
        for item in catalog
        if item.get("config")
        and item.get("config") != current
        and (
            not same_type
            or (
                item.get("type") == wanted_type
                and str(item["config"]).partition("_")[0] == wanted_family
            )
        )
    }
    return sorted(configs)


def unique_saved_items() -> list[dict[str, str | None]]:
    """Return unique carried items found across User and each main run save."""
    paths = ([USER_SAVE] if USER_SAVE.exists() else []) + [
        item["path"] for item in list_save_candidates()
    ]
    catalog: dict[str, tuple[str, str, str | None]] = {}
    for path in paths:
        try:
            obj = parse_ftk2(path.read_bytes()).get("json") or {}
            rows = party_from_run(obj) if "Entities" in obj else party_from_user(obj)
            for row in rows:
                for item in row.get("inventory") or []:
                    config = item.get("config")
                    item_type = item.get("type")
                    expansion = item.get("expansion") or "BASE"
                    custom_data = item.get("custom_data")
                    if config and item_type:
                        catalog.setdefault(
                            str(config),
                            (str(item_type), str(expansion), custom_data),
                        )
        except Exception:
            continue
    return [
        {
            "config": config,
            "type": metadata[0],
            "expansion": metadata[1],
            "custom_data": metadata[2],
        }
        for config, metadata in sorted(catalog.items())
    ]


def list_save_candidates() -> list[dict[str, Any]]:
    """Discover GameRuns mains for the sidebar."""
    items: list[dict[str, Any]] = []
    if GAME_RUNS_DIR.exists():
        mains = [
            p
            for p in GAME_RUNS_DIR.glob("*.ftk2")
            if not p.stem.rsplit("-", 1)[-1].isdigit()
        ]
        mains.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for path in mains:
            items.append(
                {
                    "label": path.name,
                    "path": path,
                    "kind": "run",
                    "mtime": path.stat().st_mtime,
                }
            )
        # Also include newest numbered slots that have a saveName-worthy size? skip for noise
    return items


def run_display_name(path: Path) -> str:
    """Human-readable name for a GameRun save: its ``saveName`` when parseable, else the filename."""
    path = Path(path)
    try:
        summary = parse_ftk2(path.read_bytes()).get("summary") or {}
        name = summary.get("saveName")
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:  # noqa: BLE001 - name is cosmetic; fall back to filename
        pass
    return path.name


def find_carryover_source(current: Path) -> Path | None:
    """Locate the most recent save slot of a *different* run (the previous act).

    Given the currently-open save, scan all ``GameRuns`` *.ftk2 files, group them
    by run id (filename stem before any trailing ``-N``), pick the most-recently
    modified run other than ``current``'s own run, and return its newest slot (or
    the bare file if no numbered slots exist).  Returns ``None`` when there is no
    other run on disk.
    """
    current = Path(current)
    files = list(GAME_RUNS_DIR.glob("*.ftk2")) if GAME_RUNS_DIR.exists() else []
    if not files:
        return None

    current_run = _run_key(current)
    by_run: dict[str, list[Path]] = {}
    for p in files:
        key = _run_key(p)
        if key == current_run:
            continue
        by_run.setdefault(key, []).append(p)

    if not by_run:
        return None

    # Newest run = the one with the latest mtime among its newest slot.
    def newest_of(paths: list[Path]) -> tuple[float, Path]:
        best = max(paths, key=lambda p: p.stat().st_mtime)
        return best.stat().st_mtime, best

    candidate_runs = sorted(
        (newest_of(paths) for paths in by_run.values()),
        key=lambda item: item[0],
        reverse=True,
    )
    return candidate_runs[0][1]


def _run_key(path: Path) -> str:
    """Stable run id: strip a trailing ``-N`` slot suffix (all-digit segment)."""
    stem = path.stem
    if stem.rsplit("-", 1)[-1].isdigit():
        stem = stem.rsplit("-", 1)[0]
    return stem


def load_save_view(path: Path) -> dict[str, Any]:
    """Parse a save into a GUI-friendly view model."""
    path = Path(path)
    data = path.read_bytes()
    parsed = parse_ftk2(data)
    obj = parsed.get("json") if isinstance(parsed.get("json"), dict) else {}
    summary = parsed.get("summary") if isinstance(parsed.get("summary"), dict) else {}

    kind = "run" if summary or "Entities" in obj else "user"
    party: list[dict[str, Any]] = []
    non_party: list[dict[str, Any]] = []
    pet_owners: set[str] = set()
    follower_bindings: dict[str, str] = {}
    stats: dict[str, Any] = {}
    overview: dict[str, Any] = {
        "path": str(path),
        "file_size": parsed.get("file_size"),
        "plaintext_size": parsed.get("plaintext_size"),
        "parse_error": parsed.get("parse_error"),
        "kind": kind,
    }

    if kind == "user":
        party = party_from_user(obj)
        stats = obj.get("LocalStats") or {}
        overview.update(
            {
                "title": "User profile",
                "version": obj.get("LastPlayedVersionString"),
                "difficulty": obj.get("LastUsedDifficulty"),
                "last_run": obj.get("LastGameRunIdPlayed"),
                "lore": stats.get("TOTAL_LORE") if isinstance(stats, dict) else None,
                "gold_collected": stats.get("GOLD_COLLECTED") if isinstance(stats, dict) else None,
                "gold_spent": stats.get("GOLD_SPENT") if isinstance(stats, dict) else None,
                "language": obj.get("Language"),
                "unlocks": len(obj.get("NewLoreStoreUnlocks") or []),
            }
        )
        # If last run exists, optionally note preferred guids for later
        preferred = [row["guid"] for row in party if row.get("guid")]
    else:
        preferred = None
        # Try to align with User party guids when available
        if USER_SAVE.exists():
            try:
                user_view = parse_ftk2(USER_SAVE.read_bytes())
                user_obj = user_view.get("json") or {}
                preferred = [
                    e.get("Guid")
                    for e in (user_obj.get("PartyCharacters") or [])
                    if isinstance(e, dict) and e.get("Guid")
                ]
            except Exception:
                preferred = None
        all_rows = party_from_entities(obj.get("Entities") or [], standard_only=False)
        party = party_from_run(obj, preferred_guids=preferred)
        party_guids = {row.get("guid") for row in party if row.get("guid")}
        # Followers (COMPANION/MERCENARY) rented or carried per-party-member are
        # legitimate editable rows; surface them alongside the main heroes.
        followers = obj.get("PlayerFollowers") if isinstance(obj, dict) else None
        if isinstance(followers, dict):
            follower_guids = {
                str(info.get("FollowerID"))
                for info in followers.values()
                if isinstance(info, dict) and info.get("FollowerID")
            }
            # A "pet owner" is a player whose bound follower is a COMPANION
            # (as opposed to a MERCENARY/other follower).
            companion_guids = {
                str(entity.get("Guid"))
                for entity in (obj.get("Entities") or [])
                if isinstance(entity, dict)
                and (entity.get("Components") or {})
                .get("CharacterComponent", {})
                .get("CharacterType")
                == "COMPANION"
            }
            for host_guid, info in followers.items():
                if not isinstance(info, dict):
                    continue
                if str(info.get("FollowerID")) in companion_guids:
                    pet_owners.add(str(host_guid))
            if follower_guids:
                follower_rows = party_from_entities(
                    obj.get("Entities") or [],
                    guids=follower_guids,
                    standard_only=False,
                )
                for row in follower_rows:
                    guid = row.get("guid")
                    if guid and guid not in party_guids:
                        party.append(row)
                        party_guids.add(guid)
        # Each host owns at most one follower (PlayerFollowers is a map), so
        # annotate the rows with the binding for display and add/remove guards.
        if isinstance(followers, dict):
            follower_bindings = {
                str(host_guid): str(info.get("FollowerID"))
                for host_guid, info in followers.items()
                if isinstance(info, dict) and info.get("FollowerID")
            }
        follows = {follower: host for host, follower in follower_bindings.items()}
        names = {
            str(row.get("guid")): row.get("name")
            for row in party
            if row.get("guid")
        }
        for row in party:
            guid = str(row.get("guid"))
            bound = follower_bindings.get(guid)
            row["follower_guid"] = bound
            row["follower_name"] = names.get(bound) if bound else None
            host = follows.get(guid)
            row["follows_guid"] = host
            row["follows_name"] = names.get(host) if host else None
        non_party = [
            row
            for row in all_rows
            if row.get("guid") not in party_guids
        ]
        stats = obj.get("Stats") or {}
        house_rules = obj.get("HouseRules")
        overview.update(
            {
                "title": summary.get("saveName") or path.stem,
                "run_id": summary.get("runID") or path.stem.rsplit("-", 1)[0],
                "adventure": summary.get("adventureType") or obj.get("ConfigName"),
                "difficulty": summary.get("difficulty") or obj.get("GameDifficulty"),
                "version": summary.get("version") or obj.get("Version"),
                "date": summary.get("dateTime"),
                "entity_count": len(obj.get("Entities") or []),
                "gold_collected": stats.get("GOLD_COLLECTED") if isinstance(stats, dict) else None,
                "gold_spent": stats.get("GOLD_SPENT") if isinstance(stats, dict) else None,
                "party_gold_total": sum((row.get("gold") or 0) for row in party),
                "house_rules": house_rules if isinstance(house_rules, dict) else None,
            }
        )

    # Slim JSON for tree: drop giant Entities list from root copy
    tree_root: dict[str, Any]
    if kind == "run" and "Entities" in obj:
        tree_root = {k: v for k, v in obj.items() if k != "Entities"}
        tree_root["Entities"] = f"<{len(obj.get('Entities') or [])} entities — see Party tab>"
        if summary:
            tree_root = {"_summary": summary, **tree_root}
    else:
        tree_root = obj

    return {
        "path": path,
        "kind": kind,
        "overview": overview,
        "party": party,
        "non_party": non_party,
        "pet_owners": pet_owners,
        "followers": follower_bindings,
        "stats": stats if isinstance(stats, dict) else {},
        "stats_rows": interesting_stats(stats if isinstance(stats, dict) else {}),
        "summary": summary,
        "tree": tree_root,
        "raw": parsed,
        "unlocks": list(obj.get("NewLoreStoreUnlocks") or []) if kind == "user" else [],
    }


# ---------------------------------------------------------------------------
# Game-asset catalogs (mercenaries, playable classes) for the party editors.
# Small static JSONs under For The King II_Data/.../Assets/Configs/JSON~ are
# read on demand and cached so repeated GUI refreshes stay cheap.  All access
# is guarded: a missing/invalid game install yields empty catalogs rather than
# raising, keeping the editor usable on systems without the game mounted.
# ---------------------------------------------------------------------------

_asset_cache: dict[tuple[str, str], Any] = {}


def _load_asset_json(name: str) -> Any:
    """Return the parsed ``JSON~/{name}`` asset dict, or ``{}`` when unavailable."""
    key = (str(FTK2_ASSETS_DIR), name)
    if key in _asset_cache:
        return _asset_cache[key]
    try:
        data: Any = {}
        path = FTK2_ASSETS_DIR / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _asset_cache[key] = data
    return data


# Non-consumable Thing classes: gear, currency and innate passives never
# appear in a "grant me a consumable" list.
_NON_CONSUMABLE_CLASSES = frozenset(
    {"WEAPON", "ATTIRE", "TRAIT", "CURRENCY", "PASSIVE", "VEHICLE", "DEBUG"}
)

# Every stackable Thing config across the game's Things/ configs.
_THINGS_FILES = ("Things/Items.json", "Things/Attires.json", "Things/Weapons.json")


def consumable_catalog() -> list[dict[str, Any]]:
    """Every stackable, usable Thing in the game's ``Things/`` configs.

    A config qualifies when it stacks (``Stacks: true``), is not hidden, is not
    gear/currency/a passive, and is *usable* — either tagged ``USEABLE`` or
    carrying at least one ``Interactable.Abilities`` entry (that second test is
    what keeps quest pieces like ``MISC_WHEELPIECE_01``, which have no USEABLE
    tag but do have ``WHEEL_PIECE_USE``).

    Each record: ``{"config", "name", "class", "rarity", "consumable_type",
    "abilities"}``.  ``name`` is the English string from ``Langs/en.json``,
    falling back to the config name when a tier variant has no entry of its
    own.  Sorted by class then name, so the GUI list groups naturally.
    """
    names = _load_asset_json("Langs/en.json")
    catalog: list[dict[str, Any]] = []
    for file_name in _THINGS_FILES:
        things = _load_asset_json(file_name)
        for config, entry in things.items():
            if not isinstance(config, str) or not isinstance(entry, dict):
                continue
            if entry.get("Hidden"):
                continue
            item_class = str(entry.get("Class") or "")
            if item_class in _NON_CONSUMABLE_CLASSES or not item_class:
                continue
            if not entry.get("Stacks"):
                continue
            if config.upper().startswith("CURRENCY_") or config.upper() == "XP":
                continue
            tags = entry.get("Tags")
            abilities = (entry.get("Interactable") or {}).get("Abilities")
            abilities = abilities if isinstance(abilities, dict) else {}
            if not abilities and not (isinstance(tags, list) and "USEABLE" in tags):
                continue
            label = names.get(config) if isinstance(names, dict) else None
            catalog.append(
                {
                    "config": config,
                    "name": str(label) if isinstance(label, str) and label else config,
                    "class": item_class,
                    "rarity": str(entry.get("Rarity") or ""),
                    "consumable_type": str(entry.get("ConsumableType") or ""),
                    "abilities": sorted(str(a) for a in abilities),
                }
            )
    catalog.sort(key=lambda row: (row["class"], row["name"].lower(), row["config"]))
    return catalog


def mercenary_catalog() -> list[dict[str, Any]]:
    """Available mercenary recruit families from ``Followers.json``.

    Each record: ``{"class_name", "config_base", "contract_rounds", "rarity",
    "tiers"}`` where ``tiers`` lists the ``_BASIC_00.._07`` levels actually
    present in ``Characters.json`` for that family (standard mercs ship 0-7;
    specials may only ship a subset).  Sorted by display label.
    """
    followers = _load_asset_json("Followers.json")
    characters = _load_asset_json("Characters.json")
    catalog: list[dict[str, Any]] = []
    for class_name, entry in followers.items():
        if not isinstance(entry, dict) or entry.get("Type") != "MERCENARY":
            continue
        base = str(entry.get("ConfigName") or "")
        if not base:
            continue
        family = base.rsplit("_BASIC_", 1)[0] if "_BASIC_" in base else base
        tiers = sorted(
            int(match.group(1))
            for key in characters
            if isinstance(key, str)
            and (match := re.search(rf"^{re.escape(family)}_BASIC_(\d+)$", key))
        )
        if not tiers:
            tiers = [0]
        catalog.append(
            {
                "class_name": class_name,
                "config_base": base,
                "contract_rounds": entry.get("ContractRounds"),
                "rarity": entry.get("Rarity"),
                "tiers": tiers,
            }
        )
    catalog.sort(key=lambda row: str(row["class_name"]))
    return catalog


def mercenary_spec(class_name: str, tier: int = 0) -> dict[str, Any] | None:
    """Build the ``add_mercenary`` spec for a recruit family and tier.

    Returns ``None`` (fail-closed) when the family is unknown, has no
    character config, or the tier is out of range.
    """
    followers = _load_asset_json("Followers.json")
    characters = _load_asset_json("Characters.json")
    entry = followers.get(class_name)
    if not isinstance(entry, dict) or entry.get("Type") != "MERCENARY":
        return None
    base = str(entry.get("ConfigName") or "")
    if not base:
        return None
    family = base.rsplit("_BASIC_", 1)[0] if "_BASIC_" in base else base

    available = sorted(
        int(match.group(1))
        for key in characters
        if isinstance(key, str)
        and (match := re.search(rf"^{re.escape(family)}_BASIC_(\d+)$", key))
    )
    if tier not in available:
        return None

    config_name = f"{family}_BASIC_{tier:02d}"
    config = characters.get(config_name)
    if not isinstance(config, dict):
        return None
    stats = config.get("Stats") if isinstance(config.get("Stats"), dict) else {}
    things = config.get("Things") if isinstance(config.get("Things"), dict) else {}
    start_things = [str(key) for key, count in things.items() if count]
    return {
        "class_name": class_name,
        "type_args": class_name,
        "config_name": config_name,
        "contract_rounds": int(entry.get("ContractRounds") or 0),
        "start_health": int(stats.get("HP") or 0),
        "start_focus": int(stats.get("FOC") or 0),
        "start_things": start_things,
    }


def playable_class_names() -> list[str]:
    """PLAYER-tagged character configs (the class-swap targets), sorted."""
    characters = _load_asset_json("Characters.json")
    names = [
        str(name)
        for name, entry in sorted(characters.items())
        if isinstance(entry, dict) and "PLAYER" in (entry.get("Tags") or [])
    ]
    return names


HEALER_PASSIVES = frozenset({"SKILL_PARTYHEAL", "SKILL_MEDIC"})


def healer_class_names() -> set[str]:
    """Character configs whose passives mark them as healers/medics.

    The save stores only a character's ``ConfigName`` (its class), never its
    passives, so healing ability has to be derived from ``Characters.json``:
    any config whose ``Passives`` include ``SKILL_PARTYHEAL`` or ``SKILL_MEDIC``
    (in the base game, HERBALIST and MONK).  Empty when assets are missing.
    """
    characters = _load_asset_json("Characters.json")
    return {
        str(name)
        for name, entry in characters.items()
        if isinstance(entry, dict)
        and HEALER_PASSIVES.intersection(entry.get("Passives") or [])
    }


_comp_family_re = re.compile(r"^(.*)_\d+$")


def _companion_tiers(family: str) -> list[int]:
    """Tier levels actually present for a companion ``<_family>`` prefix."""
    characters = _load_asset_json("Characters.json")
    return sorted(
        int(match.group(1))
        for key in characters
        if isinstance(key, str)
        and (match := re.match(rf"^{re.escape(family)}_(\d+)$", key))
    )


def companion_catalog() -> list[dict[str, Any]]:
    """Available pet/companion recruit families from ``Followers.json``.

    Each record: ``{"class_name", "config_base", "contract_rounds", "rarity",
    "tiers"}`` where ``tiers`` lists the levels actually present in
    ``Characters.json`` for the family (companions usually ship 0-7).
    Companion families with no resolvable character config (e.g.
    ``COMPANION_REFLECTION``) are omitted. Sorted by display label.
    """
    followers = _load_asset_json("Followers.json")
    catalog: list[dict[str, Any]] = []
    for class_name, entry in followers.items():
        if not isinstance(entry, dict) or entry.get("Type") != "COMPANION":
            continue
        base = str(entry.get("ConfigName") or "")
        if not base:
            continue
        match = _comp_family_re.match(base)
        family = match.group(1) if match else base
        tiers = _companion_tiers(family)
        if not tiers:
            continue
        catalog.append(
            {
                "class_name": class_name,
                "config_base": base,
                "contract_rounds": entry.get("ContractRounds"),
                "rarity": entry.get("Rarity"),
                "tiers": tiers,
            }
        )
    catalog.sort(key=lambda row: str(row["class_name"]))
    return catalog


def companion_spec(class_name: str, tier: int = 0) -> dict[str, Any] | None:
    """Build the ``add_pet`` spec for a companion family and tier.

    Returns ``None`` (fail-closed) when the family is unknown, has no
    character config, or the tier is out of range. Pets spawn with no gear;
    ``add_pet`` adds 50 kibble and an XP counter automatically.
    """
    followers = _load_asset_json("Followers.json")
    characters = _load_asset_json("Characters.json")
    entry = followers.get(class_name)
    if not isinstance(entry, dict) or entry.get("Type") != "COMPANION":
        return None
    base = str(entry.get("ConfigName") or "")
    if not base:
        return None
    match = _comp_family_re.match(base)
    family = match.group(1) if match else base

    available = _companion_tiers(family)
    if tier not in available:
        return None

    config_name = f"{family}_{tier:02d}"
    config = characters.get(config_name)
    if not isinstance(config, dict):
        return None
    stats = config.get("Stats") if isinstance(config.get("Stats"), dict) else {}
    return {
        "class_name": class_name,
        "type_args": class_name,
        "config_name": config_name,
        "contract_rounds": int(entry.get("ContractRounds") or 0),
        "start_health": int(stats.get("HP") or 0),
        "start_focus": 1,  # real companion entities carry 1 focus
        "start_things": [],
    }
