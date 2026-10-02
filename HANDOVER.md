# HANDOVER

Current state of **ftk2-save-editor** as of 2026-10-02. For the reasoning and
evidence behind any of this, see [`JOURNAL.md`](JOURNAL.md).

## Do this first

**The 2026-10-01 save-corruption fix is uncommitted.** It lives entirely in the
working tree on branch `fix/follower-placement-and-party-tools`, not on `main`:

| File | Change |
|---|---|
| `src/ftk2_editor/__init__.py` | UTF-16-code-unit `xor_crypt`, `escape_non_bmp`, `dump_json_for_game`, `SaveVerificationError`, `verify_game_readable`, `write_save` |
| `src/ftk2_editor/gui.py` | all 19 write sites routed through `write_save` |
| `src/ftk2_editor/cli.py` | all 3 write sites routed through `write_save` |
| `tests/test_ftk2_editor.py` | 12 regression tests |
| `README.md`, `decompiled/FORMAT.md` | corrected format claim + write-verification section |

It is one `rm` from gone. Tests pass (`191 passed`, verified by stashing back to
the 179-test baseline). It needs a commit and a decision about whether it belongs
on `main` before more work starts on top of it.

## What the bug was

`xor_crypt` indexed the `21398xa2` key per Python **code point**. The game
(`decompiled/SaveGameHelper.cs:561-583`) advances the key per **UTF-16 code
unit**, so an astral character consumed two positions where the editor consumed
one. From the first emoji onward, everything decrypted to garbage — and the game
rejected the save while the editor still read its own output back perfectly.

Trigger: a Hall-of-Heroes stone hero named `🐉可是帝王之征啊` at
`Entities[6228]`. Two incidents (21:45 and 22:39 on 2026-10-01), same cause.

Fixed and verified: decrypt→re-encrypt of a game-written save is byte-identical,
and the game's own read path (`/tmp/opencode/ftk2repro`) accepts the output.

## Verification, and its limits

`verify_game_readable()` / `write_save()` mirror the game's read path and are now
the gate on every write. They are stricter than `ftk2-edit --verify-only`, which
still reports "All checks passed" on a `GameRuns/*.ftk2` it cannot read — that
flag does not parse a run body (see `JOURNAL.md`).

The ground-truth harness lives in `/tmp/opencode/ftk2repro` and **will not
survive a reboot**:

```bash
cd /tmp/opencode/ftk2repro && dotnet exec bin/Debug/net10.0/repro.dll <file.ftk2>
```

Recreate it from the `Program.cs` there if needed. Nothing in Python can
authoritatively answer "would the game read this".

## Open work

### 1. Named save snapshots with one-click rollback — NOT STARTED

Requested explicitly. The live `.bak.N` rotation is **not** a substitute: no
names, no UI, and it rotates out.

Everything needed is already in place: `backup()` takes the first free
`.bak`/`.bak.N`, and `write_save()` verifies before replacing. A snapshot feature
is a naming scheme plus a restore path, not a new safety mechanism.

The `.bak` … `.bak.14` chain in the live `GameRuns/` dir is intact and should stay
that way. `.bak.7` (22:34:02, 5796694 bytes, 6520 entities) is the
furthest-progressed game-loadable state.

Pre-repair originals, including both corrupted files:
`~/code/games/ftk2/repair-backup-2026-10-01/`.

### 2. Five BepInEx mod ideas — NOT STARTED, and NOT save-editor work

Existing infra: `~/code/games/ftk2/ftk2-rest-party-panel` — BepInEx 5.4.23.5,
Harmony 2, Mono, net472, 646 lines, `RestPartyPanel.dll` installed at
`…/For The King II/BepInEx/plugins/`, HEAD `575147f`.

1. In the shop, buy and send to another character.
2. In the shop, buy a stack of N.
3. Distribute what you bought across the party.
4. **The big one** — a shared party inventory usable outside the dungeon,
   behaving like the dungeon's.
5. Companion health on the overworld, as it appears at rest inside a dungeon.
   Small extension of `RestPartyPanel`, which already fills
   `combat-detail-holder-left` via `CombatDetailHolderViewHelper.ShowDetails` on
   the rest route.

**Blocker, raised 2026-10-01 and still unanswered.** FTK2 replays a deterministic
ordered action stream over Photon in co-op — the logs show
`_orderedGameActionMessageCount`, `DesyncData.Hash`, and `GameRandomNextInt`.
Ideas 1–4 mutate state outside the game's own action pipeline and will probably
desync co-op sessions. Pick one before writing code:

- **single-player only** — cheapest, and honest about the limit;
- **host-authoritative** — the host applies the change and it flows through the
  normal action path;
- **route through a real game action** — most correct, most work.

Idea 5 is unaffected: `CombatVisualAction` carries no `DesyncData.Hash`, so it is
outside the ordered replay stream.

### 3. Latent mod bugs — observed, never investigated

Historical log errors, none in the current session:

- `KeyNotFoundException` for `MERC_TOADSLAYER_BASIC_02_M`,
  `MERC_BOMBER_BASIC_02_M`, `COMPANION_SPIDER_BASIC_02_F`
  ("not present in the dictionary"). Note these three are **not** in the game's
  current `Characters.json`/`Followers.json`.
- `COMPANION_BAT_BASIC_01/02 … not found in gameObjectMap, rendering nothing`.
  These two **are** in the current configs — a different cause from the above.

Not present in the current save: all 49 STANDARD/COMPANION configs the live save
references (644 across all 98 runs) cross-check clean against `Characters.json`
and `Followers.json`.

### 4. Cosmetic red in the logs — no action needed

- `Failed to find an animation controller for SHIELD STANDARD` — 34 in one older
  session, 87 in the current one, 126 in the cumulative log.
- 2× `NullReferenceException` at `CombatPhase.get__activeCharacterEntity` via
  `TryPlayNetworkTransientGameAction`, both in an older session.

Both cosmetic: `CombatVisualAction` carries no `DesyncData.Hash`, so it is
outside the ordered replay stream, and the surrounding authoritative actions
consumed normally.

## Housekeeping gaps

- **CI runs pytest only.** No lint, no typecheck
  (`.github/workflows/build-release.yml`). No pre-commit hook, no `core.hooksPath`.
  The 12 regression tests are the only thing preventing a reintroduction of the
  key-indexing bug, and nothing forces them to run before a commit.
- **`.tools/bin/ilspycmd` is broken** — absolute path from before the repo moved.
  `decompiled/FORMAT.md` and `decompiled/HOWTO.md` now document the working
  invocation instead; the wrapper script itself is still stale.
- **Game logs are under the install dir**, not the Proton prefix, and
  `BepInEx/LogOutput.log` is cumulative (13.8 MB). Scope any read to the last
  `BepInEx 5.4.23.5` banner line.
- `SKILL.md` (owned by `teacher`, not by this repo's docs) still describes the
  XOR as "every character" and omits the code-unit rule — see the handover
  report; it needs a `teacher` pass, not a local edit.