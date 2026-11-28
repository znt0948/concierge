# Running Stardew Valley on a Steam Deck (WOPR)

This fork (`znt0948/concierge`) is the base Concierge plus the patches that made
an imported Fluorine/MO2 Stardew Valley instance playable and maintainable on a
Steam Deck running SteamOS. Upstream is `msmfai/concierge`; nothing here is
upstream behaviour unless noted.

Everything below is the state of the reference machine (`wopr`, `deck` user).

**Status (2026-11-28):** live. `concierge-cli v0.12.1-wopr.8` is installed, the
profile is realized (200 mods, `doctor` clear), native Steam AppID `413150`
launches the instance, and the temporary non-Steam test shortcut has been
removed. The Fluorine/MO2 instance is untouched and remains the rollback path.

## What the fork changes

| Change | Why it is needed |
| --- | --- |
| Preserve the top-level mod folder for `modfolders` games (Stardew/SMAPI) | Upstream applied its Bethesda archive heuristic and stripped the wrapper directory, so every mod's `manifest.json` landed directly in `Mods/` and overwrote the previous one. SMAPI requires `Mods/<ModName>/manifest.json`. |
| Lenient SMAPI `manifest.json` parsing (UTF-8 BOM, CRLF, trailing commas) | Many Stardew mods ship BOM/CRLF manifests; the linter called dozens of them `unparseable-manifest` and then reported bogus `missing-dependency` violations. |
| `config.json` and `.ogg`/`.wav` deploy as writable copies, not store hardlinks | SMAPI mods rewrite `config.json` at startup; MonoGame/FNA opens audio files read-write. A 0444 hardlink into the read-only store made both fail with `Access to the path ... is denied`. Placement shape is now part of the up-to-date check, so an older install is repaired by the next `realize`. |
| `concierge-cli i18n --lang <code>` | Reports SMAPI translation coverage per mod: complete, partial (keys missing from `<lang>.json`) or absent. |

Helper scripts for the one-time import and the bulk update live in
`scripts/`; they are WOPR-specific and not part of the upstream product.

## Layout on the Deck

| Path | Content |
| --- | --- |
| `/home/deck/.local/bin/concierge-cli` | The CLI. Keep the previous binary beside it when upgrading (`concierge-cli.pre-woprN-<stamp>`). |
| `/home/deck/concierge-test/stardew-full/` | The profile: `manifest.toml`, `builds/`, `state/` (plan, realized state, backups). This is what `CONCIERGE_REPO` points at. |
| `/home/deck/concierge-test/stardew-full-instance/` | The modded game copy. `Mods/` is owned by Concierge; the pristine install is never touched. |
| `/home/deck/concierge-test/full-archives/` | Local `file://` archives created by the Fluorine importer. |
| `/home/deck/.local/share/Steam/steamapps/common/Stardew Valley` | Pristine Steam install (1.6.15). |
| `/home/deck/.config/StardewValley/ErrorLogs/SMAPI-latest.txt` | SMAPI log: load list, skipped mods, runtime errors, update alerts. |
| `/home/deck/.config/concierge/nexus-api-key` | Nexus Personal API key, `deck:deck 0600`, internal SSD only. |

`CONCIERGE_REPO` is the only required environment variable:

```sh
export CONCIERGE_REPO=/home/deck/concierge-test/stardew-full
CONCIERGE=/home/deck/.local/bin/concierge-cli
```

## Everyday commands

```sh
$CONCIERGE eval        # manifest -> plan (checks layout/dependencies, writes state/plan.json)
$CONCIERGE realize     # fetch + build + deploy into the instance (idempotent)
$CONCIERGE doctor      # pins, lints, empty dirs, drift, pristine safety
$CONCIERGE check       # drift only
$CONCIERGE status      # per-mod pipeline state
$CONCIERGE preview     # what a realize would change, without changing it
```

`realize` is the single apply step: it re-deploys changed mods, replaces stale
read-only hardlinks, prunes files that left the manifest, and re-applies
configuration. `realize --fresh` re-clones the instance from pristine and wipes
the recorded state (use after a Stardew game update, see below).

`doctor` is the acceptance gate. `[PASS]` everywhere is healthy. `[WARN] no
empty dirs` is expected: a few mod packages ship empty directories (for example
`SaveAndLoadCharacterPresets/presets`). `[FAIL] no drift` means the instance was
modified outside Concierge — run `realize`.

## Importing an existing Fluorine/MO2 profile (one time)

```sh
python3 scripts/import-fluorine-stardew.py \
  --fluorine-dir /home/deck/.local/share/fluorine/bin/stardew \
  --profile Default \
  --pristine "/home/deck/.local/share/Steam/steamapps/common/Stardew Valley" \
  --instance /home/deck/concierge-test/stardew-full-instance \
  --archives-dir /home/deck/concierge-test/full-archives \
  --out-manifest /home/deck/concierge-test/stardew-full/manifest.toml
```

The importer walks `profiles/<profile>/modlist.txt` in reverse (MO2 priority is
last-wins), wraps each mod folder in a `file://` ZIP, copies the Nexus id and
version out of `meta.ini`, pins the MD5, and writes `manifest.toml`. Skipped
rows are printed; an MO2 separator is not a mod.

## Updating mods

Discovery is SMAPI's own update check. Every `ALERT SMAPI]` line in
`SMAPI-latest.txt` names the Nexus mod id and the new version; the runner
resolves it through the Nexus API and only accepts a single unambiguous `MAIN`
file:

```sh
python3 scripts/update-stardew-mods.py \
  --repo /home/deck/concierge-test/stardew-full \
  --smapi-log /home/deck/.config/StardewValley/ErrorLogs/SMAPI-latest.txt \
  --api-key-file /home/deck/.config/concierge/nexus-api-key
```

It backs up `manifest.toml` first, rewrites the chosen `[[mod]]` blocks with
`nexus_mod_id` / `nexus_file_id`, runs `eval`, `fetch` (Premium CDN, TOFU MD5),
writes the pinned MD5s back, then `realize` and `doctor`. It skips:

- mods where the SMAPI name does not map to exactly one manifest entry
  (content pack / main mod pairs, renamed folders);
- mods with more than one `MAIN` file (manual variant choice required);
- mods whose archive is not a plain single-main-file package.

Skipped mods are the ones to handle by hand; they are not failures. A mod that
introduces an uninstalled hard dependency makes `realize` fail its lint — add
the dependency (e.g. `BlinkFix` for `Soft Farmer`) or revert that one block from
the backup.

Rollback: restore `manifest.toml.bak-<UTC>` and run `realize` again. The
instance is derived from the manifest, so a manifest rollback is a full mod
rollback.

## Translation coverage

```sh
$CONCIERGE i18n --lang zh
```

Reports `N full, M partial (missing keys), K missing zh.json`, then per-mod
detail sorted by missing keys. A second pass reports `suspicious`: mods whose
`<lang>.json` contains values byte-identical to `default.json` - the "copied the
file, translated only part of it" case. Values without letters (numbers, `%s`,
`^`, bare tokens) are ignored, since those are legitimately identical.

```sh
i18n (zh): 50 full, 20 partial (missing keys), 41 missing zh.json
  suspicious: 3 mod(s) with values identical to default
...
Suspicious (value identical to default.json - likely untranslated):
  Some Mod — 12/321 values identical
``` Mods that ship translations as a separate mod
(`[CP] ... Chinese Translation`) show up as `missing` here even though the game
is localized.

Machine translation is deliberately not wired in yet. When it is, the plan is a
DeepSeek-compatible API with a fixed Stardew glossary in the system prompt and
strict preservation of `{{tokens}}`, `$h`, `^`, `#$b#` and JSON structure;
Google/DeepL free tiers do not support per-game glossary/context and regularly
break those placeholders. Only missing keys would be filled; existing human
translations are never overwritten.

## Launching through Steam

The native Steam entry (`Stardew Valley`, AppID `413150`) is the launch point:
Steam Cloud and the Steam overlay only work for the real app id, not for an
invented non-Steam shortcut.

Concierge's instance is started by a wrapper that Steam runs through the app's
launch options. **The wrapper must execute Steam's launch chain**, not SMAPI
directly:

```sh
# /home/deck/.local/bin/concierge-stardew
#!/usr/bin/env bash
set -euo pipefail
INSTANCE=/home/deck/concierge-test/stardew-full-instance
PRISTINE_PAYLOAD="/home/deck/.local/share/Steam/steamapps/common/Stardew Valley/StardewValley"

args=("$@")
for i in "${!args[@]}"; do
  case "${args[$i]}" in
    "$PRISTINE_PAYLOAD"|*/"steamapps/common/Stardew Valley/StardewValley")
      args[$i]="$INSTANCE/StardewValley" ;;
  esac
done
exec "${args[@]}"
```

and `LaunchOptions` for `413150` is:

```
bash /home/deck/.local/bin/concierge-stardew %command%
```

Steam substitutes `%command%` with
`steam-launch-wrapper ... reaper SteamLaunch AppId=413150 -- SteamLinuxRuntime_soldier/... -- <game>/StardewValley`.
That chain has to run: the **reaper** is what tells the Steam client the game
started, and Gaming Mode keeps its "launching" spinner overlay on top of the
game until it does. Executing `./StardewModdingAPI` from the wrapper instead
(the pre-2026-11-28 wrapper) still runs the game - the SMAPI log reaches the
title screen - but in Gaming Mode the screen stays on the spinning Steam logo
and the game is invisible behind it. Desktop Mode shows the window normally,
which makes this look like "it works" when testing over SSH.

The instance's `StardewValley` is SMAPI's launcher script, so the rewritten
payload still starts SMAPI (and now under the Steam runtime, with the overlay).
The old direct-exec wrapper is kept as
`/home/deck/.local/bin/concierge-stardew.bak-direct-exec` for reference only.

The previous value (`bash /home/deck/.local/share/applications/stardew-Stardew-Valley.sh %command%`,
the Fluorine `moshortcut://` launcher) is backed up to
`Agent/backups/steam-shortcuts/<UTC>-concierge-native-entry/` before the edit.

Rollback: restore the backed-up launch options, restart Steam, verify the
Fluorine launcher still opens.

## Translation packs (overlay mods)

Most Stardew translations ship as an overlay: a mod whose files live under
`<target mod folder>/i18n/zh.json` (sometimes also `<target>/Data/*.json`) and
are merged into the target mod. MO2 does that merge in its VFS; Concierge
deploys literal paths, so the overlay only works when `<target>` is exactly the
deployed folder path.

A mod update can change that layout (a Nexus zip that roots the mod at
`Trolley Expansion/` while the imported copy and its translation used `[CP] TE`),
and then the overlay files land outside any mod folder. SMAPI reports them as
"contains files, but none of them are manifest.json" - they are **not** junk;
deleting them drops the translation.

Since `v0.12.1-wopr.7`, a mod can declare where its files go instead of
repackaging the archive:

```toml
[mod.config]
# optional: archive folder treated as the install root (strips a wrapper)
subdir = "[CP] Aquatic Sea Fish/Aquatic Sea Fish"
# optional: destination prefix inside the install root (always ends in "/")
prefix = "[CP] Aquatic Sea Fish/"
```

`subdir` picks what to take, `prefix` says where to put it. `prefix` is
validated at eval time (no absolute paths, no `.`/`..`). The destination must
match the installed mod folder **exactly**, including spaces vs hyphens -
`[CP] Canon Friendly Dialogue Expansion` is not
`[CP] Canon-Friendly Dialogue Expansion`.

- 2026-11-28 examples: Aquatic Sea Fish translation (Nexus 49544) uses
  `subdir` + `prefix`; Canon-Friendly Dialogue Expansion translation (Nexus
  54094) ships a bare `zh.json` and uses
  `prefix = "[CP] Canon Friendly Dialogue Expansion/i18n/"`.
- Older repair (before `prefix` existed): repackage the archive with the new
  prefix, repin `md5`, then `realize`. Trolley `[CP] TE/*` ->
  `Trolley Expansion/[CP] TE/*` and `Lots of Kisses/*` -> `LotsOfKisses/*`.
- Before rewriting a pack that carries `Data/*.json`, verify its JSON key
  structure matches the installed mod (a stale translation would delete newer
  content). `i18n --lang zh` then confirms the keys are found.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Skipped mods ... because it contains files, but none of them are manifest.json` | A wrapper folder holds the real mod one level deeper, or an old file was left at the top of a mod folder. | Check `Mods/<name>/manifest.json`; the folder must be the mod root. Remove stray files, `realize`. |
| `Access to the path '.../config.json' is denied` | A 0444 store hardlink from an older deploy. | Run `realize` (this fork re-places writable copies); verify `stat -c %a` is not 444. |
| `Error loading sound: ... is denied` | Same, for `.ogg`/`.wav`. | Same. |
| `unparseable-manifest` for many mods | BOM/CRLF manifests, fixed in this fork's linter. | Rebuild with a current `v0.12.1-wopr.*` binary. |
| Gaming Mode shows the spinning Steam logo while `SMAPI-latest.txt` shows a normal load | The wrapper executed SMAPI directly, so Steam's reaper never reported the launch. | Re-exec Steam's `%command%` chain with the payload rewritten to the instance (see "Launching through Steam"). |
| Game exits slowly / Steam hangs in "running" | Wrapper exported a `SteamAppId` that does not match the launching entry. | Remove the export; let Steam provide the environment. |
| `doctor` reports `no drift` FAIL after playing | The game wrote `config.json` files (SMAPI saves settings). | Since `v0.12.1-wopr.6` runtime-mutable `config.json` is excluded from drift; other modifications are still reported. Saves live in `~/.config/StardewValley`, not the instance. |

## Upgrading the binary

Releases are pre-release tags `v0.12.1-wopr.N` on `znt0948/concierge`, built by
the `Release binaries` workflow. Install without touching the profile:

```sh
gh release download v0.12.1-wopr.N --repo znt0948/concierge \
  -p 'concierge-v0.12.1-wopr.N-x86_64-linux.tar.gz' -D /tmp --clobber
scp /tmp/concierge-v0.12.1-wopr.N-x86_64-linux.tar.gz wopr:/tmp/
ssh wopr 'sudo bash -c "
  set -e
  tar -xzf /tmp/concierge-v0.12.1-wopr.N-x86_64-linux.tar.gz -C /tmp
  cp /home/deck/.local/bin/concierge-cli /home/deck/.local/bin/concierge-cli.pre-woprN-\$(date -u +%Y%m%dT%H%M%SZ)
  install -o deck -g deck -m 0755 \
    /tmp/concierge-v0.12.1-wopr.N-x86_64-linux/concierge-cli \
    /home/deck/.local/bin/concierge-cli
"'
```

Then `realize` and `doctor` once with the new binary. The profile and instance
are forward/backward compatible within `v0.12.1-wopr.*`.
