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
cd ftk2-save-editor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
# Summary of User.ftk2
ftk2-edit --info

# Decrypt to editable JSON
ftk2-edit --decrypt /tmp/User.json

# Re-encrypt after editing
ftk2-edit --encrypt-from /tmp/User.json --output /tmp/User.ftk2

# Patch a LocalStats value (re-encrypts in place; use --backup)
ftk2-edit --backup --set LocalStats.SOME_STAT=999

# Verify decrypt works
ftk2-edit --verify-only
```

## Warnings

- Edit a **copy**, or always use `--backup`
- Quit the game first — it overwrites `User.ftk2` on exit
- Steam Cloud may overwrite local edits
- `GameRuns/*.ftk2` are large expedition states; prefer editing `User.ftk2` unless you know the schema

## Decompiled sources

`decompiled/*.cs` are ILSpy output from `FTK2.dll` (research only).  
Local decompiler SDK lives under `.tools/` (gitignored).
