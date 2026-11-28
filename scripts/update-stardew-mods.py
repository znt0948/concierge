#!/usr/bin/env python3
"""Safely update unambiguous single-MAIN Stardew mods in a Concierge manifest.toml.

Reads SMAPI-latest.txt update alerts, queries Nexus API for each mod's MAIN files,
skips any mod with != 1 MAIN file or ambiguous manifest mapping, updates manifest.toml,
runs `concierge-cli fetch`, auto-pins MD5s, and runs `concierge-cli realize`.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def parse_smapi_alerts(log_path: Path) -> dict[int, tuple[str, str, str]]:
    """Return {nexus_mod_id: (display_name, new_ver, old_ver)}."""
    alerts: dict[int, tuple[str, str, str]] = {}
    pat = re.compile(
        r"ALERT SMAPI\]\s+(.+?)\s+([^\s:]+):\s+https://www\.nexusmods\.com/stardewvalley/mods/(\d+)\s+\(you have ([^)]+)\)"
    )
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.search(line)
        if m:
            name, new_ver, mod_id, old_ver = m.group(1).strip(), m.group(2).strip(), int(m.group(3)), m.group(4).strip()
            alerts[mod_id] = (name, new_ver, old_ver)
    return alerts


def nexus_main_files(api_key: str, mod_id: int) -> list[dict]:
    url = f"https://api.nexusmods.com/v1/games/stardewvalley/mods/{mod_id}/files.json"
    req = urllib.request.Request(url, headers={"apikey": api_key, "User-Agent": "wopr-concierge-updater/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    return [f for f in data.get("files", []) if f.get("category_name") == "MAIN"]


def slugify(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "mod"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--smapi-log", required=True, type=Path)
    ap.add_argument("--api-key-file", required=True, type=Path)
    ap.add_argument("--concierge-bin", default="/home/deck/.local/bin/concierge-cli")
    args = ap.parse_args()

    api_key = args.api_key_file.read_text(encoding="utf-8").strip()
    manifest_path = args.repo / "manifest.toml"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = args.repo / f"manifest.toml.bak-{ts}"
    shutil.copy2(manifest_path, backup_path)
    print(f"Backup: {backup_path}")

    alerts = parse_smapi_alerts(args.smapi_log)
    print(f"Found {len(alerts)} unique Nexus mod IDs in SMAPI alerts.")

    text = manifest_path.read_text(encoding="utf-8")
    # Split into header + [[mod]] blocks
    parts = re.split(r"(?m)^(?=\[\[mod\]\]$)", text)
    header = parts[0]
    blocks = parts[1:]

    # Map nexus_mod_id -> list of block indices (from manifest.toml OR builds/<md5>/**/manifest.json UpdateKeys)
    id_to_indices: dict[int, list[int]] = {}
    builds_dir = args.repo / "builds"
    nexus_key_re = re.compile(r'"Nexus:(\d+)"', re.I)
    for idx, blk in enumerate(blocks):
        found_ids: set[int] = set()
        m_id = re.search(r"(?m)^nexus_mod_id\s*=\s*(\d+)\s*$", blk)
        if m_id:
            found_ids.add(int(m_id.group(1)))
        else:
            m_md5 = re.search(r'(?m)^md5\s*=\s*"([a-f0-9]{32})"\s*$', blk)
            if m_md5:
                bdir = builds_dir / m_md5.group(1)
                if bdir.is_dir():
                    for mf in bdir.rglob("manifest.json"):
                        try:
                            raw = mf.read_text(encoding="utf-8", errors="replace")
                            for nid in nexus_key_re.findall(raw):
                                found_ids.add(int(nid))
                        except Exception:
                            pass
        for nid in found_ids:
            id_to_indices.setdefault(nid, []).append(idx)

    updated: list[tuple[str, str, str, int, int]] = []
    skipped: list[tuple[str, str]] = []

    for mod_id, (smapi_name, new_ver, old_ver) in sorted(alerts.items()):
        indices = id_to_indices.get(mod_id, [])
        if len(indices) != 1:
            skipped.append((smapi_name, f"ambiguous manifest match ({len(indices)} entries for nexus_mod_id={mod_id})"))
            continue

        try:
            mains = nexus_main_files(api_key, mod_id)
        except Exception as e:
            skipped.append((smapi_name, f"Nexus API error: {e}"))
            continue

        if len(mains) != 1:
            skipped.append((smapi_name, f"has {len(mains)} MAIN files (needs manual/choice selection)"))
            continue

        f = mains[0]
        file_id = int(f["file_id"])
        file_ver = str(f.get("version") or new_ver).strip()
        ext = Path(f.get("file_name", "mod.zip")).suffix or ".zip"

        idx = indices[0]
        blk = blocks[idx]
        m_name = re.search(r'(?m)^name\s*=\s*"(.*)"\s*$', blk)
        if not m_name:
            skipped.append((smapi_name, "could not parse mod name in manifest"))
            continue
        mod_name = m_name.group(1)
        fname = f"{slugify(mod_name)}-{mod_id}-{slugify(file_ver)}{ext}"

        new_blk = (
            f"[[mod]]\n"
            f'name = "{mod_name}"\n'
            f'version = "{file_ver}"\n'
            f"nexus_mod_id = {mod_id}\n"
            f"nexus_file_id = {file_id}\n"
            f'file = "{fname}"\n'
            f'md5 = ""\n'
            f"enabled = true\n\n"
        )
        blocks[idx] = new_blk
        updated.append((mod_name, old_ver, file_ver, mod_id, file_id))

    manifest_path.write_text(header + "".join(blocks), encoding="utf-8")
    print(f"\nPrepared {len(updated)} unambiguous updates, skipped {len(skipped)}:")
    for name, old_v, new_v, mid, fid in updated:
        print(f"  + {name}: {old_v} -> {new_v} (mod={mid}, file={fid})")
    print("\nSkipped:")
    for name, reason in skipped:
        print(f"  - {name}: {reason}")

    if not updated:
        print("Nothing to fetch/realize.")
        return

    env = dict(os.environ)
    env["CONCIERGE_REPO"] = str(args.repo)
    env["LANG"] = "en_US.UTF-8"
    env["LC_ALL"] = "en_US.UTF-8"

    print("\n=== EVAL ===")
    subprocess.run([args.concierge_bin, "eval"], env=env, check=True)

    print("\n=== FETCH (Premium CDN + TOFU MD5) ===")
    proc = subprocess.run([args.concierge_bin, "fetch"], env=env, capture_output=True, text=True)
    out = proc.stdout + "\n" + proc.stderr
    pin_pat = re.compile(r'PIN\s+(.+?):\s+set md5 = "([a-f0-9]{32})"')
    pins = dict(pin_pat.findall(out))
    print(f"Fetched & captured {len(pins)} MD5 pins.")
    if len(pins) < len(updated):
        print("Warning: some pins missing; fetch output tail:")
        print("\n".join(out.splitlines()[-30:]))

    # Write pins back into manifest.toml
    text2 = manifest_path.read_text(encoding="utf-8")
    parts2 = re.split(r"(?m)^(?=\[\[mod\]\]$)", text2)
    h2, blks2 = parts2[0], parts2[1:]
    for i, blk in enumerate(blks2):
        m_name = re.search(r'(?m)^name\s*=\s*"(.*)"\s*$', blk)
        if m_name and m_name.group(1) in pins:
            blks2[i] = blk.replace('md5 = ""', f'md5 = "{pins[m_name.group(1)]}"', 1)
    manifest_path.write_text(h2 + "".join(blks2), encoding="utf-8")

    print("\n=== REALIZE ===")
    subprocess.run([args.concierge_bin, "realize"], env=env, check=True)
    print("\n=== DOCTOR ===")
    subprocess.run([args.concierge_bin, "doctor"], env=env, check=False)


if __name__ == "__main__":
    main()
