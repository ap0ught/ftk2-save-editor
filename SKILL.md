---
name: ftk2-save-editor
description: "Read, parse, and edit For The King II (FTK2) save files on Linux — XOR-obfuscated JSON (key 21398xa2). Wallet gold is CURRENCY_ADVENTURE._stackCount on CharacterComponent.Things; LocalStats GOLD_* are lifetime counters."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [gaming, steam, proton, save-editor, python, FTK2, For-The-King-II]
    related_skills: [steam-proton-game-data]
  edit_file:
    path: ~/.local/share/Steam/steamapps/compatdata/1676840/pfx/drive_c/users/steamuser/AppData/LocalLow/IronOak Games/For The King II/User.ftk2
    backup: true
---
# FTK2 Save Editor

## Overview

Save editor for **For The King II** (Steam appid 1676840). Reads/writes `User.ftk2` under the Proton prefix.

## Format (from FTK2.dll)

Confirmed by decompiling `SaveGameHelper` in `FTK2.dll`:

1. Serialize `UserData` / `GameRunData` with **System.Text.Json** (indented)
2. XOR every character with repeating key **`21398xa2`**
3. Write UTF-8 text with BOM (`EF BB BF`) as `.ftk2`

Also: `.ftk2z` = LZ4 path; `.json` = unencrypted path (in code).

`GameRuns/*.ftk2` decrypt to `//**{summary}**//\n{GameRunData JSON}`.

See `decompiled/FORMAT.md` (schema), `decompiled/HOWTO.md` (decompile → key), and `decompiled/SaveGameHelper.cs`.

## Gold and party data

- **Wallet gold** (what you spend in-run): inventory Thing `CURRENCY_ADVENTURE` → `_stackCount` on  
  `GameRunData.Entities[].Components.CharacterComponent.Things[]`
- **Not wallet gold:** `UserData.LocalStats.GOLD_COLLECTED` / `GOLD_SPENT` and `GameRunData.Stats.GOLD_*` (lifetime / run stats)
- **Lore (meta):** `LocalStats.TOTAL_LORE`; item id `CURRENCY_LORE`
- **XP:** Thing `ConfigName == "XP"` → `_stackCount`
- Party identity: `CharacterComponent.DisplayName`, `ConfigName` (class), `CurrentHealth`, `CurrentFocus`

## Save location

```text
~/.local/share/Steam/steamapps/compatdata/1676840/pfx/drive_c/users/steamuser/AppData/LocalLow/IronOak Games/For The King II/User.ftk2
```

Game runs: same folder under `GameRuns/`.

## Usage

```bash
cd /home/cmayfield/code/games/SE/ftk2-save-editor
source .venv/bin/activate   # or: python3 -m venv .venv && pip install -e .

ftk2-gui   # desktop reader (party gold, inventory, stats, JSON)

ftk2-edit --info
ftk2-edit --decrypt /tmp/User.json
ftk2-edit --encrypt-from /tmp/User.json --output /tmp/User.ftk2
ftk2-edit --set LocalStats.TOTAL_LORE=500
ftk2-edit --no-backup --set LocalStats.SOME_STAT=999
ftk2-edit --verify-only

# Expedition wallet: decrypt a GameRuns/*.ftk2 and edit CURRENCY_ADVENTURE._stackCount
ftk2-edit GameRuns/<uuid>.ftk2 --decrypt /tmp/run.txt
```


## Caveats

- Quit the game before editing; it overwrites `User.ftk2` on exit
- Steam Cloud can overwrite local edits
- Editing gold requires the **GameRun** file, not only `User.ftk2`
- `GameRunData.Entities` lists are very large — prefer targeted edits

## Related

- `decompiled/` — ILSpy output + format notes (`FORMAT.md` has gold/schema detail)
- `steam-proton-game-data` skill for Proton paths
