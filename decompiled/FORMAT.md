# FTK2 save format (from FTK2.dll decompile)

Source: `SaveGameHelper` in `For The King II_Data/Managed/FTK2.dll`  
Decompiled with `ilspycmd` → `SaveGameHelper.cs`, `UserData.cs`, `GameRunData.cs`.

## Pipeline

```text
C# object (UserData / GameRunData)
  → System.Text.Json (JsonHelper.Serialize*, indented)
  → XOR each char with repeating key "21398xa2"
  → UTF-8 text file with BOM  (EF BB BF)
  → *.ftk2
```

Decrypt is the same XOR (symmetric).

```csharp
private static readonly string encryptString = "21398xa2";

private static char _encryptOrDecryptChar(char pChar, int pIndex)
{
    return (char)(pChar ^ encryptString[pIndex % encryptString.Length]);
}
```

Indices are **Unicode character** indices after UTF-8 decode (as `StreamReader` / string XOR), not raw byte indices.

## Extensions

| Extension | Meaning |
|-----------|---------|
| `.ftk2`   | XOR-encrypted JSON (what Steam/Proton uses) |
| `.ftk2z`  | LZ4-compressed (optional header `//**…**//`) — not common on disk here |
| `.json`   | Plain JSON (debug / unencrypted path in code) |

## Files on disk

- `User.ftk2` — `UserData` JSON (settings, `LocalStats`, lore unlocks, party presets, etc.)
- `GameRuns/<uuid>.ftk2` — XOR of:
  ```text
  //**{GameSaveDirector.GameSaveData summary}**//
  {GameRunData JSON…}
  ```
- `GameRuns/<uuid>-N.ftk2` — manual / checkpoint slots for the same run

## Schema cheat sheet

### `UserData` (`User.ftk2`)

Useful top-level fields:

| Field | Notes |
|-------|--------|
| `PartyCharacters` / `LastRunCharacters` | `Entity` lists (avatar/loadout snapshots; **not** live expedition wallets) |
| `LocalStats` | Lifetime / meta counters (`dict[str,int]`) |
| `NewLoreStoreUnlocks` | Lore store unlock id strings |
| `LastGameRunIdPlayed` | UUID matching a `GameRuns/<uuid>.ftk2` |
| `LastUsedDifficulty` / `LastPlayedVersionString` | Meta |

**`LocalStats` gold/lore keys (lifetime — not current wallet):**

| Key | Meaning |
|-----|---------|
| `GOLD_COLLECTED` | Lifetime gold picked up |
| `GOLD_SPENT` | Lifetime gold spent |
| `TOTAL_LORE` | Current lore currency balance (meta) |
| `LORE_POINTS_SPENT` | Lore spent in the store |
| `LORE_STORE_PURCHASES` | Purchase count |
| `CHALLENGE_PB~…_GOLD_COLLECTED` | Per-adventure personal-best gold collected |

Also present: item unlock flags like `BAG_OF_GOLD_01`, kill tags like `TAGS_KILLED_GOLDENPLAINS` — these are **not** wallet gold.

### `GameRunData` (`GameRuns/*.ftk2`)

After the `//**summary**//` header, the body is `GameRunData`. Important fields:

| Field | Notes |
|-------|--------|
| `ConfigName` | Adventure id (e.g. `STORY_1_3`) |
| `GameDifficulty` | e.g. `APPRENTICE` |
| `Entities` | Huge list of all map entities (players, NPCs, props, …) |
| `Stats` | Per-run counters (`GOLD_COLLECTED`, `GOLD_SPENT`, per-player variants) |
| `ItemPools` | Includes `CURRENCY_LORE` (pool, not party gold) |
| `AdventureState` | Map / weather / pools / etc. |

Summary header (`GameSaveDirector.GameSaveData`) typically has: `runID`, `saveName`, `difficulty`, `adventureType`, `version`, `dateTime`.

### Party characters inside a run

Player characters are `Entity` objects in `Entities` with:

```text
Components.CharacterComponent.DisplayName
Components.CharacterComponent.ConfigName      # class, e.g. HERBALIST
Components.CharacterComponent.CurrentHealth
Components.CharacterComponent.CurrentFocus
Components.CharacterComponent.Things[]        # inventory + passives + currency
Components.CharacterComponent.Equipped        # slot → thing id
Components.AdventureComponent.MapID / HexPosition
Components.PlayerComponent                    # AP, movement flags, …
```

`Things[]` entries look like:

```json
{
  "Id": "<uuid>",
  "ConfigName": "CURRENCY_ADVENTURE",
  "Type": "ITEM",
  "_stackCount": 127,
  "Expansion": "BASE"
}
```

## Gold (wallet)

**Current gold on a character is not a numeric field named `Gold`.**  
It is an inventory stack:

| | |
|-|-|
| Item id | `CURRENCY_ADVENTURE` |
| Location | `Entity.Components.CharacterComponent.Things[]` |
| Amount | `_stackCount` |
| Related meta currency | `CURRENCY_LORE` (lore; often in `ItemPools` / store, not party gold) |

To read party wallets from a decrypted run:

1. Find player entities (`CharacterComponent.CharacterType == "STANDARD"` with a `DisplayName`, or match guids from `UserData.PartyCharacters`).
2. In each `Things` list, find `ConfigName == "CURRENCY_ADVENTURE"`.
3. Use `_stackCount` as that character’s gold.

`GameRunData.Stats` / `UserData.LocalStats` `GOLD_COLLECTED` / `GOLD_SPENT` are **statistics**, not the coins you spend in shops.

XP is likewise a Thing: `ConfigName == "XP"`, amount in `_stackCount`.

## Important correction

Earlier notes calling this “protobuf-like binary” were wrong.  
`protobuf-net.dll` is present in Managed/ (likely networking / other systems).  
**Saves are JSON + XOR**, not protobuf-net on disk.

## Decompiler tooling (local)

```bash
export DOTNET_ROOT="$PWD/.tools/dotnet"
export PATH="$DOTNET_ROOT:$PWD/.tools/bin:$PATH"
ilspycmd "/path/to/Managed/FTK2.dll" -t SaveGameHelper -r "/path/to/Managed" > decompiled/SaveGameHelper.cs
```

`.tools/` is gitignored (portable .NET SDK + ilspycmd).

Narrative of how the key was found: [`HOWTO.md`](HOWTO.md).

## Round-trip check

```bash
ftk2-edit --decrypt /tmp/User.json
# edit JSON
ftk2-edit --encrypt-from /tmp/User.json --output /tmp/User.ftk2 --backup
```
