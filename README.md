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
cd /home/cmayfield/code/games/ftk2/ftk2-save-editor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Uses **PySide6** for the GUI (no system `tk` package required).

## GUI

```bash
ftk2-gui
```

Browse `User.ftk2` and `GameRuns/*.ftk2`: overview, party wallets (`CURRENCY_ADVENTURE`), inventory, stats, and a trimmed JSON tree. Export decrypted JSON from **File → Export**.

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
