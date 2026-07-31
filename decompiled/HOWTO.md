# How this viewer was built

Research notes for the For The King II save reader: how we went from opaque
`.ftk2` blobs to a working PySide6 viewer.

## Context

- Game: **For The King II** (Steam appid `1676840`), Unity **2021.3**
- Saves (Proton):  
  `~/.local/share/Steam/steamapps/compatdata/1676840/pfx/drive_c/users/steamuser/AppData/LocalLow/IronOak Games/For The King II/`
- Files of interest: `User.ftk2`, `GameRuns/<uuid>.ftk2`, `GameRuns/<uuid>-N.ftk2`
- Game assemblies:  
  `…/steamapps/common/For The King II/For The King II_Data/Managed/`  
  especially `FTK2.dll` and (red herring) `protobuf-net.dll`

Early guesses assumed a generic Unity save format (PlayerPrefs, Easy Save, NRBF /
`BinaryFormatter`, or protobuf-net on disk). None of those open `.ftk2` files.
The real path was: **decompile the game’s own save helper**.

## Step 1 — Fingerprint the on-disk file

`User.ftk2` starts with a UTF-8 BOM (`EF BB BF`) then high-entropy-looking text.
It is not gzip, zip, JSON, or Easy Save. String scans show garbled fragments
like `42XA` — later understood as XOR’d JSON punctuation / field names.

## Step 2 — Decompile `FTK2.dll`

Tooling (also under `.tools/`, gitignored):

1. Portable **.NET 8 SDK**
2. **ilspycmd** 9.1 (net8) from NuGet
3. Decompile save-related types with the Managed folder as references:

```bash
export DOTNET_ROOT="$PWD/.tools/dotnet"
export PATH="$DOTNET_ROOT:$PWD/.tools/bin:$PATH"

MANAGED="$HOME/.local/share/Steam/steamapps/common/For The King II/For The King II_Data/Managed"

ilspycmd "$MANAGED/FTK2.dll" -t SaveGameHelper -r "$MANAGED" > decompiled/SaveGameHelper.cs
ilspycmd "$MANAGED/FTK2.dll" -t UserData       -r "$MANAGED" > decompiled/UserData.cs
ilspycmd "$MANAGED/FTK2.dll" -t GameRunData    -r "$MANAGED" > decompiled/GameRunData.cs
```

`strings` / `monodis` on `FTK2.dll` already pointed at:

- `SaveGameHelper`, `_writeEncryptedContents`, `_readEncryptedFile`
- `_encryptOrDecrypt`, `LZ4Compress` / `K4os.Compression.LZ4`
- `COMPRESSED_FILE_FORMAT` (`.ftk2z`), `UNENCRYPTED_FILE_FORMAT` (`.json`),
  `ENCRYPTED_FILE_FORMAT` (`.ftk2`)

## Step 3 — Find the key

In decompiled `SaveGameHelper.cs`:

```csharp
private static readonly string encryptString = "21398xa2";

private static char _encryptOrDecryptChar(char pChar, int pIndex)
{
    return (char)(pChar ^ encryptString[pIndex % encryptString.Length]);
}
```

Write path for `.ftk2`:

1. `JsonHelper.Serialize*` → indented **System.Text.Json**
2. XOR each **Unicode character** with repeating key `21398xa2`
3. Write UTF-8 text (typically with BOM)

Decrypt is the same XOR (symmetric). Indices are character indices after UTF-8
decode, not raw file-byte indices.

`protobuf-net.dll` is in Managed but is **not** the on-disk save codec (likely
networking / other systems). Saves are **JSON + XOR**.

## Step 4 — Prove the round-trip

Decrypting a live `User.ftk2` with that key yields valid JSON (`PartyCharacters`,
`LocalStats`, settings, …). Re-encrypting with the same algorithm produces a
file the game accepts (after quitting the game / watching Steam Cloud).

Game runs decrypt to:

```text
//**{summary JSON}**//
{GameRunData JSON…}
```

## Step 5 — Map “gold” and party data

Wallet gold is **not** `LocalStats.GOLD_*` (those are lifetime counters).

It is an inventory Thing on each character:

| | |
|-|-|
| Item | `CURRENCY_ADVENTURE` |
| Path | `GameRunData.Entities[].Components.CharacterComponent.Things[]` |
| Amount | `_stackCount` |

XP is the Thing `ConfigName == "XP"`. Lore meta balance is
`UserData.LocalStats.TOTAL_LORE`. Full schema notes: [`FORMAT.md`](FORMAT.md).

## Step 6 — Build the tools

| Piece | Role |
|-------|------|
| `ftk2_editor` | XOR decrypt/encrypt, parse User vs GameRun |
| `viewmodel.py` | Party / gold / stats extraction for UI |
| `ftk2-edit` | CLI (`--info`, `--decrypt`, `--set`, …) |
| `ftk2-gui` | PySide6 viewer (overview, party, inventory, stats, JSON tree) |

PySide6 was chosen because system `tk` / `libtk` was not installed on this host.

## Reproducing decompilation later

```bash
# After installing .tools as above
ilspycmd "$MANAGED/FTK2.dll" -t SaveGameHelper -r "$MANAGED" | rg -n "encryptString|_encryptOrDecrypt"
```

If IronOak changes the key or codec, re-decompile `SaveGameHelper` and update
`ENCRYPT_KEY` in `src/ftk2_editor/__init__.py`.

## Legal / safety

Decompiled C# under `decompiled/` is for personal research against a game you
own. Do not redistribute game binaries. Always backup saves before writing;
quit the game first; Steam Cloud can overwrite local files.
