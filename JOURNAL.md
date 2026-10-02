# ftk2-save-editor run journal

Working notes so a future session starts from the findings instead of
rediscovering them. Newest entry at the bottom. Times are CDT unless the source
says otherwise.

This repo had no journal, `HANDOVER.md`, `AGENTS.md`, or `docs/` before
2026-10-02, and none has ever existed in its git history (44 commits, 21 tracked
files). `JOURNAL.md` at the root is therefore the default layout, not an
inherited one.

---

## 2026-10-02 — journal established; a live FTK2 campaign could not load, twice

### Where things stood

Branch `fix/follower-placement-and-party-tools`, HEAD `c06f204`
("fix: place followers on the map, guard the follower slot, party tools",
2026-09-29 09:53:16 -0500), in sync with `origin/` (0 commits behind).

**Nothing from the 2026-10-01 repair session was committed.** As of this entry
the working tree carried 6 modified files (+354/-30) — the entire save-corruption
fix, uncommitted and on a feature branch that is not `main`. Committing it is
the first thing to do in any future session; the diff is one `rm` from gone. This
entry adds `JOURNAL.md`, `HANDOVER.md`, and two `decompiled/*.md` corrections.

```
$ .venv/bin/python -m pytest -q
191 passed in 1.07s
```

191 pass (179 pre-existing + 12 new). Verified by stashing the whole tree:
baseline is 179, so the 12 new tests are additive and the pre-existing suite is
unaffected. There is no lint or typecheck in CI
(`.github/workflows/build-release.yml` runs `python -m pytest -q` and nothing
else), and no pre-commit hook and no `core.hooksPath`.

### The bug: key stream indexed per code point instead of per UTF-16 code unit

Two incidents, same root cause. Game exited 21:45:47; the editor ran 21:45–21:50
and wrote `GameRuns/24c8851d-66b4-49ae-a008-d292757343c8.ftk2` seven times
(`.bak` … `.bak.6`). Game relaunched 21:50:12, Continue failed. After the repair
the editor ran again at 22:39 (`/tmp/ftk2-gui.log` mtime 22:39) and wrote the run
8 more times (`.bak.8` → live), and the same corruption returned.

The game's read path, `decompiled/SaveGameHelper.cs:561-583`:

```csharp
using StreamReader sourceStream = await FileIO.OpenText(pFilePath);  // File.OpenText => UTF-8
while (!sourceStream.EndOfStream)
{
    char pChar = (char)sourceStream.Read();       // ONE UTF-16 code unit per call
    pChar = _encryptOrDecryptChar(pChar, num++);  // key index advances PER CODE UNIT
    targetStream.Write(pChar);
}
```

`StreamReader.Read()` returns one UTF-16 code unit, so an astral character is a
surrogate pair and consumes **two** key positions. The editor's `xor_crypt`
indexed the key per Python code point, so an emoji consumed one. The 8-char key
(`21398xa2`) desynchronised at the first non-BMP character and everything after
it decrypted to garbage.

The trigger was a Hall-of-Heroes stone hero named `🐉可是帝王之征啊`, at
`Entities[6228]` of the `.bak.7` snapshot:

```
$ .venv/bin/python -c "...print(Entities[6228].Components.HeroComponent)"
HeroConfigName: 5e562376-f031-4bb3-bb27-8c16710ef406
HeroDifficulty: LOAD_GAME_UI_DIFFICULTY_GAUNTLET
HeroDisplayName: 🐉可是帝王之征啊
```

Its `CharacterComponent.CharacterType` is `PROP` and `ConfigName` is `HUNTER`, so
it is a `HeroComponent` statue, not a party member. Any entity carrying an
astral character would have done it.

The game's own error, from the cumulative `BepInEx/LogOutput.log:84372` (session
banner at 84007) — note the Path, which names the exact entity:

```
JsonReaderException: '0x07' is invalid within a JSON string.
  LineNumber: 175410 | BytePositionInLine: 57
Rethrow as JsonException: ... Path: $.Entities[6228]
  SaveGameHelper._readRunDataAsync -> _readEncryptedFile<T>
  NetworkHelper.ContinueSaveGameAsHost
  AdventureSelectionDirector._onlineMultiplayerOnContinueSaveGameAsHost
```

Incident 2, `LogOutput.log:86974`, same shape: `'/' is an invalid start of a
value`, `Path: $.Entities[6228]`, LineNumber 174752.

**Contributing factor.** `dump_user_json` and friends used
`json.dumps(..., ensure_ascii=False)`, writing the emoji as raw UTF-8. The game's
own saves store it escaped, astral-only, BMP CJK left raw — confirmed on the
game-written `.bak.7`:

```
'HeroDisplayName": "\\uD83D\\uDC09可是帝王之征啊",\r\n
raw U+1F409 present? False
```

**Why it was silent.** The editor read its own output back perfectly, because it
decrypted with the same wrong indexing. A self-consistent round trip is not
evidence of a correct one.

### Ruled out

**The `.bak` chain is entirely the editor's.** Initially assumed. False, and it
matters for reasoning about which writes were ours. The live `GameRuns/` dir
holds `.bak` … `.bak.14` with **no** editor run between 22:22 and 22:34, while
`output_log.txt` records the game saving `24c8851d-…` repeatedly
(`grep -n 'Saving gamerun 24c8851d'` → 15 hits in one session). The game writes
`.bak.N` too. The editor's `backup()` (`src/ftk2_editor/__init__.py`) takes the
first free `.bak`, `.bak.1`, `.bak.2`… which is why editor and game writes
interleave in that chain rather than forming two separate series.

**`Backups/` is the game's, not ours.** `…/For The King II/Backups/` holds
`User-backup-<uuid>.ftk2` files with the game's own naming and timestamps, and
the editor's `backup()` never writes there.

**A fast Python emulation of the game XOR cleared every save.** It reported all
~180 saves clean, *including the known-broken one*. The cause was UTF-16-LE byte
order reversed: a code unit's **low** byte sits at even offsets, and I had XORed
the high byte at odd offsets. This produced a clean bill of health twice — once
here, once in a scanner. **Validate a fast re-implementation against the real
thing before trusting it.** Measuring the same file through the correct
game-faithful loop gives **111,319** raw control characters (excluding CR/LF) in
the body — the garbage is real and large. (An earlier figure of 128,490 in my own
notes does not reproduce; use the measured 111,319.)

### The decisive diagnostic

A verbatim C# port of `SaveGameHelper._readEncryptedFile`, throwaway project at
`/tmp/opencode/ftk2repro` (`Program.cs`, net10.0). This harness is the ground
truth for every repair claim. Run it with:

```bash
cd /tmp/opencode/ftk2repro && dotnet exec bin/Debug/net10.0/repro.dll <file.ftk2>
```

Verified this session:

| File | Result |
|---|---|
| `repair-backup-2026-10-01/…ftk2.corrupt` (incident 1) | `FAILED … '0x07' is invalid within a JSON string. LineNumber: 175409` |
| `repair-backup-2026-10-01/…ftk2.broken-2241` (incident 2) | `FAILED … '/' is invalid after a value. LineNumber: 174751` |
| live `GameRuns/24c8851d-….bak.7` (game-written) | `PARSED OK, Entities = 6520` |

The harness reproduces the game's *exact* error class on both broken files and
`PARSED OK` on the game's own pre-edit backup. Note its LineNumber is one lower
than the game's (175409 vs 175410) because the game counts the `//**summary**//`
header line; the entity index in the Path matches.

The Python `verify_game_readable()` agrees on **line numbers** for both broken
files (175410, 174752) and differs only in column convention (40 and 39 vs the
game's 57 and 56). Line agreement is the check that matters; column is a
different counting rule, not a disagreement.

### Fix (uncommitted — see above)

- `xor_crypt` (`src/ftk2_editor/__init__.py:61`) rewritten to be UTF-16-code-unit
  indexed. Every key char is `< 0x100`, so only a unit's low byte changes and the
  high byte — which is what distinguishes the surrogate ranges — is preserved;
  a `bytearray` slice plus `bytes.translate` over an `lru_cache`d 256-byte table
  is equivalent and fast. Multi-byte keys are rejected.
- New `escape_non_bmp()` / `dump_json_for_game()` emit non-BMP as `\uXXXX\uXXXX`
  surrogate pairs, matching the game. Wired into `dump_user_json`, `edit_field`,
  `_dump_json_matching_newlines`, and the GUI JSON export.
- New `SaveVerificationError`, `verify_game_readable()` (decrypt the way the game
  will, parse, report line/column) and `write_save()` (verify **before** touching
  disk, then temp file plus `os.replace`). All write sites in `gui.py`/`cli.py`
  route through it; `grep '\.write_bytes(' src/ftk2_editor/{gui,cli}.py` is now
  empty (exit 1), with 19 `write_save(` call sites in `gui.py` and 3 in `cli.py`.
- 12 regression tests. **They have teeth:** replacing `xor_crypt` with the old
  code-point version (via a `pytest -p` plugin) makes **3** of them fail —
  `test_xor_crypt_advances_the_key_twice_for_an_astral_character`,
  `test_xor_crypt_rejects_a_multibyte_key`, and
  `test_verify_game_readable_rejects_a_key_desynced_payload`.

Round-trip proof against a game-written file: decrypting and re-encrypting
`.bak.7` with the new code reproduces the file **byte-identically**
(`again == d` → `True`, 5796694 bytes).

### Findings

**`ftk2-edit --verify-only` gives a false all-clear on a corrupt run save.**
`verify_save()` (`src/ftk2_editor/__init__.py`) only `json.loads` when the
plaintext starts with `{`; a `GameRuns/*.ftk2` starts with `//**{summary}**//`, so
its body is never parsed. Measured on the incident-1 broken file:

```
$ .venv/bin/python -m ftk2_editor.cli '…/24c8851d-….ftk2.corrupt' --verify-only
Decrypts to JSON-like: True
All checks passed.        # exit 0
```

`verify_game_readable()` (new) raises on the same file at line 175410. The README
now says plainly that `--verify-only` is shallow. The pre-existing flag was not
changed; `write_save()` is what actually gates writes.

**`repair_follower_placement()` returns `changed=True` even when it repairs
nothing.** Measured on three game-written checkpoints of the same run:

| Checkpoint | bound followers with Adventure+Venue | `repair_follower_placement` |
|---|---|---|
| `25292fe1-…-3` | 4 / 4 | `changed=True, repaired=0` |
| `25292fe1-…-4` | 0 / 4 | `changed=True, repaired=4` |
| `25292fe1-…-5` | 4 / 4 | `changed=True, repaired=0` |

The returned bytes are the input unchanged (the function returns early), and the
docstring says to compare the guid list rather than the bytes — so it is not a
bug. It is recorded because `changed` is the wrong name for it and a caller that
trusts it will think it wrote.

### Ruled out (assertions I had to correct)

**"Followers lacking `VenueComponent` are invisible."** I flagged all four as
broken per the README's rule, then disproved it: checkpoints of the same run
alternate (`-3` = 4/4 with venue, `-4` = 0/4, `-5` = 4/4). The game only attaches
a venue when the party is inside one; 0/4 is correct on the overworld. A venue
is not a health signal. The README's rule is about what the **editor** must write
when it recruits, which is different from what the game writes everywhere.

**"`MaxHealth: None` on party members is suspicious."** It is not a field on
`CharacterComponent` at all. Decompiled `CharacterComponent` (via ilspycmd) has
`CurrentHealth`, `CurrentFocus`, `ExtraLives`, `NecroLives`, `BaseStatModifiers`,
`OverrideStats` — and no `MaxHealth`. `CharacterHelper.GetMaxHealth(Entity,
bool)` derives it from `GetStat(HP)` plus `level * VIT * 0.13` for players, and
`CharacterHelper.GetHealthMissing` is just `GetMaxHealth - CurrentHealth`.
Measured across 98 readable run saves, 26,690 `CharacterComponent`s, and
**zero** carry a `MaxHealth` key. It is absent in every run on disk.

### Open

- **Action item 1 (not started).** Archive/restore of a chosen save: named
  snapshots plus one-click rollback to a chosen point. Explicitly requested. The
  live `.bak.N` rotation is not a substitute — no names, no UI, and it rotates.
  - `HANDOVER.md` for the full description.
- **Five BepInEx mod ideas (not started, NOT save-editor work).** Existing infra:
  `~/code/games/ftk2/ftk2-rest-party-panel` (BepInEx 5.4.23.5 / Harmony 2 / Mono /
  net472, 646 lines, `RestPartyPanel.dll` installed in the game at
  `…/For The King II/BepInEx/plugins/`, HEAD `575147f`). Idea 5 (companion health
  on the overworld) is a small extension of it — it already fills
  `combat-detail-holder-left` via `CombatDetailHolderViewHelper.ShowDetails` on the
  rest route.
  - **Unresolved blocker, raised and not yet answered:** FTK2 replays a
    deterministic ordered action stream over Photon in co-op. `LogOutput.log`
    shows `_orderedGameActionMessageCount`, `DesyncData.Hash`, and
    `GameRandomNextInt`. Ideas 1–4 mutate state outside the game's own action
    pipeline and will likely desync co-op sessions. Needs a decision:
    single-player only, host-authoritative, or routed through a real game action.
- **Latent mod bugs, observed but never investigated.** Historical
  `KeyNotFoundException` for `MERC_TOADSLAYER_BASIC_02_M`, `MERC_BOMBER_BASIC_02_M`,
  `COMPANION_SPIDER_BASIC_02_F` "not present in the dictionary", and
  `COMPANION_BAT_BASIC_01/02 … not found in gameObjectMap, rendering nothing`.
  Three occurrences of the first kind (`LogOutput.log:31927,32409,32898`) and six
  of the second (`:54655,55923,57022,58091,59580,61169`) — all in **old**
  sessions, none in the current one. Note: the three `_M`/`_F` ids are **not**
  present in the game's current `Characters.json`/`Followers.json`, while
  `COMPANION_BAT_BASIC_01/02` **are** — so the two errors have different causes.
  Not present in the current save: 49 STANDARD/COMPANION configs referenced by
  the live save and 644 across all 98 runs, all cross-checking clean against
  `Characters.json` + `Followers.json` (2142 known configs, 0 unknown).
- **Cosmetic red in logs (current session).** `Failed to find an animation
  controller for SHIELD STANDARD` — 34 in the 84474 session, 87 in the current
  (87246) session; 126 across the cumulative log. And 2×
  `NullReferenceException` at `CombatPhase.get__activeCharacterEntity` via
  `TryPlayNetworkTransientGameAction` (`LogOutput.log:86542,86550`, session 84474
  — so historical, not current). Cosmetic: `CombatVisualAction` carries no
  `DesyncData.Hash`, so it is outside the ordered replay stream, and the
  surrounding authoritative actions consumed normally.

### Environment facts worth keeping

- FTK2 is **Mono**, not IL2CPP, under Proton.
- Game logs live under the *install* dir, not the Proton prefix:
  `~/.local/share/Steam/steamapps/common/For The King II/output_log.txt`
  (per-session, truncated each launch) and
  `…/For The King II/BepInEx/LogOutput.log` (cumulative, now 13.8 MB over 101,480
  lines). **Scope any read to the last `BepInEx 5.4.23.5` banner line** or old
  errors look current — that is how the "current session" counts above were
  separated from history.
- `.tools/bin/ilspycmd` carries an absolute path from before the repo moved and
  fails with `No such file or directory`. Working invocation, now documented in
  `decompiled/FORMAT.md` and `decompiled/HOWTO.md`:
  ```bash
  export DOTNET_ROOT="$PWD/.tools/dotnet"
  ILSPY=("$PWD/.tools/dotnet/dotnet" exec "$PWD/.tools/nupkgs/extract-good/tools/net8.0/any/ilspycmd.dll")
  "${ILSPY[@]}" "$MANAGED/FTK2.dll" -t SaveGameHelper -r "$MANAGED"
  ```
- `FileIO` is **not** in `FTK2.dll`. It lives in `PlayEveryWare.dll` in the same
  `Managed/` folder, which is why `decompiled/SaveGameHelper.cs` references a type
  that is not in the assembly it was decompiled from.
- Game config assets: `…/For The King II_Data/StreamingAssets/Assets/Configs/JSON~`
  — `Characters.json`, `Followers.json`, and per-thing dirs. `Characters.json` and
  `Followers.json` are flat dicts keyed by config name.

### Artifacts preserved

- `~/code/games/ftk2/repair-backup-2026-10-01/` — pre-repair originals: 9 files,
  including `…ftk2.corrupt` (incident-1 broken bytes), `…ftk2.broken-2241`
  (incident-2 broken bytes), and 7 `.bak*.corrupt` copies.
- The `.bak` … `.bak.14` chain in the live `GameRuns/` dir is **intact** and was
  deliberately left alone — it is evidence, and `.bak.7` (22:34:02, 5796694 bytes,
  `PARSED OK, Entities = 6520`) is the furthest-progressed game-loadable state.
- `/tmp/opencode/ftk2repro` — the C# ground-truth harness. **This is in `/tmp` and
  will not survive a reboot.** Recreate it from the 40-line `Program.cs` there if
  it is gone; it is the only thing that can settle a "would the game read this"
  question authoritatively.

### Live save state, measured at end of session

The campaign was still being played, so the live file keeps moving. Recorded
here so a future session does not mistake the churn for damage:

| When | File | Bytes | Result |
|---|---|---|---|
| 23:40 | `/tmp/opencode/ftk2repro/real.bak` (kept by the repair session) | 5879706 | `PARSED OK, Entities = 6579` |
| 23:48 | `/tmp/opencode/ftk2repro/real.ftk2` (end-to-end rename test) | 5879710 | `PARSED OK, Entities = 6579` |
| 23:55 | live `GameRuns/24c8851d-….ftk2` | 5751477 | `PARSED OK, Entities = 6475` |
| 00:07 | same live file | 5751477 | `PARSED OK, Entities = 6485` |

The two 23:4x readings are the real-data end-to-end check: a hero renamed to
`J Monk ✦` and gold set, using the editor's own functions on the 5.8 MB save,
and the game still reads it. The live file then moved because **the campaign was
still being played** — the count changed between two reads of the *same* bytes.
Do not treat a changing entity count as corruption; check `PARSED OK` instead.
`User.ftk2` was also rewritten at 00:01.