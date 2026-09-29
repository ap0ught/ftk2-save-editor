# ftk2-save-editor

Save editor for **For The King II** (Steam appid 1676840) on Linux / Proton.

## Format (confirmed via FTK2.dll decompile)

`.ftk2` files are **UTF-8 BOM + XOR-obfuscated JSON**, not protobuf.

- Key: `21398xa2` (`SaveGameHelper.encryptString`)
- Payload: indented `System.Text.Json` for `UserData` / `GameRunData`
- Details: [`decompiled/FORMAT.md`](decompiled/FORMAT.md)

### Gold

Wallet gold is the inventory item **`CURRENCY_ADVENTURE`** on each party member:

`GameRuns/<uuid>.ftk2` → `Entities[].Components.CharacterComponent.Things[]` → `ConfigName == "CURRENCY_ADVENTURE"` → **`_stackCount`**

`LocalStats.GOLD_COLLECTED` / `GOLD_SPENT` (and run `Stats.GOLD_*`) are lifetime/run **stats**, not spendable coins. Lore meta balance is `LocalStats.TOTAL_LORE`.

## Save location

```text
~/.local/share/Steam/steamapps/compatdata/1676840/pfx/drive_c/users/steamuser/AppData/LocalLow/IronOak Games/For The King II/User.ftk2
```

## Install

```bash
cd /home/cmayfield/code/games/SE/ftk2-save-editor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Uses **PySide6** for the GUI (no system `tk` package required).

## GUI

```bash
ftk2-gui
```

Browse `User.ftk2` and `GameRuns/*.ftk2`: overview, party wallets (`CURRENCY_ADVENTURE`), inventory (with selected-character and whole-party top-up helpers for herbs, drinks, tools, scrolls, safetystones, thrown items, orbs, candy, and ink), stats, and a trimmed JSON tree. Export decrypted JSON from **File → Export**.

The consumable top-up helpers raise every herb stack to **15** (Scholar's Wort to **10** — it is the one herb that grants XP rather than healing, and its config `Value` is 10), every other supported stack to **10**, give a pet owner's kibble (`TOOL_KIBBLE_01`) **50**, and give a healer/medic's godsbeard (`HERB_GODSBEARD_01`) **50**. Healing is derived from the class passives (`SKILL_PARTYHEAL`/`SKILL_MEDIC`, i.e. HERBALIST and MONK) since saves store only the class name; kibble is left untouched for characters without a companion pet.

Party editing for expedition (`GameRuns/*.ftk2`) saves also includes, in the Party tab:

- One action bar under the table: **Gold** (with presets), **Name**, a single **Apply & save** that writes whichever of the two changed, then **Followers…** and **More actions**. Each character row still shows its **Follower** binding (`has <name>` for a host, `pet of <host>` for a follower); the view also exposes `followers` (`host guid → follower guid`). A host can hold **one** follower (`PlayerFollowers` is a map), so recruiting is disabled until the slot is freed.
- **Followers…** — one dialog for both follower kinds. Pick a hero and it lists their current follower (with **Remove follower**) or a single dropdown of every recruitable mercenary and pet (`name · kind · tier range`) plus a **Tier** spinner and **Recruit & save**. Pick a follower row and the same dialog offers only its removal. Recruitment stats come from the game's `Followers.json`/`Characters.json`; the follower is bound via `PlayerFollowers`, spawns beside the party, and a new pet gets **50 kibble** (`TOOL_KIBBLE_01`).
- **More actions** — party-wide tools that need no selection: **Set gold for whole party** (uses the Gold field, followers/mercs excluded), **Top up party consumables**, **Top up party snacks to 10**, **Give Carnival Wheel piece** (one `MISC_WHEELPIECE_01`, full-heal reward, to the selected character), **Create evil reflection…** (mirrors the selected hero into a Dark Carnival Evil Reflection — a bound `COMPANION` with the hero's own class, `TypeArgs: COMPANION_REFLECTION`, `Properties: [EVIL, REFLECTION]`, `DisplayName: "Evil <hero>"`, it is weaker than its host (72-75% of the host's health, focus capped at 3, matching both reference reflections), and it takes no stat or skin overrides. The hero's gear and consumables are cloned with fresh ids and every equipped slot is remapped onto the reflection's own copy (a slot whose item was not mirrored is emptied, so nothing dangles); the wallet and XP counters start at zero so a reflection is never a second purse. It refuses while the hero already has a follower unless **Replace** is ticked), **Give consumable to party…** (a filterable dropdown of every stackable consumable in the game's `Things/` configs — 135 of them, with English names — plus a count spinner defaulting to 15; every party member is raised to that count, and anyone holding none is *given* a fresh stack, unlike the top-up helpers which only raise what already exists), **Fix invisible followers** (back-fills the map placement of any bound follower that has none, see below), and **Swap class** to any playable class config (`CharacterComponent.ConfigName` only — HP/gear/levels are kept).

A follower is only drawn by the game if its entity carries **both** `AdventureComponent` (the host's hex + map) and `VenueComponent` (a 1x1 venue on a free tile beside the host). A bound follower saved without them — the shape the game uses for *unbound* recruit templates — is alive in the save but never appears on the map. `add_pet`/`add_mercenary` write both, and **Fix invisible followers** repairs followers already in a save that lack them (idempotent; healthy followers are untouched). A host's slot is also never overwritten: recruiting into an occupied `PlayerFollowers` entry fails closed instead of orphaning the previous follower.

The recruit/class catalogs are populated from your local For The King II install (`.../For The King II_Data/StreamingAssets/Assets/Configs/JSON~`); the menu entries stay disabled if the game assets can't be found. Every write creates a `.bak` backup.

## Window layout

The **Swap class** submenu is a real popup (`QMenu(parent)`, never
`QMenu().setParent(w)` — the `QWidget` overload drops the `Qt.Popup` flag and
turns the menu into a child widget painted over the party table and the action
bar, swallowing clicks on More actions).  The Saves sidebar has a 280px floor
and the split is re-applied on first show, because `setSizes()` during
`__init__` is discarded before the splitter has a geometry and the pane would
otherwise collapse to its 112px `minimumSizeHint`.

## CLI

```bash
# Summary of User.ftk2 (backup by default)
ftk2-edit --info

# Skip backup (be careful)
ftk2-edit --no-backup --set LocalStats.SOME_STAT=999

# Decrypt to editable JSON
ftk2-edit --decrypt /tmp/User.json

# Re-encrypt after editing
ftk2-edit --encrypt-from /tmp/User.json --output /tmp/User.ftk2

# Write to a different file instead of overwriting
ftk2-edit --output /tmp/Patched.ftk2 --set LocalStats.SOME_STAT=999

# Verify decrypt works
ftk2-edit --verify-only
```

## Warnings

- Edit a copy, or use `--output` to write elsewhere
- `--no-backup` skips the default backup; use with caution
- Quit the game first — it overwrites `User.ftk2` on exit
- Steam Cloud may overwrite local edits
- `GameRuns/*.ftk2` are large expedition states; prefer editing `User.ftk2` unless you know the schema

## Decompiled sources

`decompiled/*.cs` are ILSpy output from `FTK2.dll` (research only).
Local decompiler SDK lives under `.tools/` (gitignored).
