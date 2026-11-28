#!/usr/bin/env python3
"""Import an existing Fluorine/MO2 Stardew Valley instance into a Concierge manifest.toml.

Reads `profiles/<profile>/modlist.txt` (in reverse order so MO2 priority maps
to Concierge's last-in-wins order), packages each enabled mod into a local zip
archive (preserving top-level mod folders and excluding `meta.ini`), computes
its MD5 pin, and writes `manifest.toml`.
"""

import argparse
import configparser
import hashlib
import os
import re
import zipfile
from pathlib import Path


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return s or "mod"


def toml_str(val: str) -> str:
    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def read_meta_ini(mod_dir: Path) -> tuple[int | None, str]:
    meta = mod_dir / "meta.ini"
    if not meta.is_file():
        return None, "local"
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(meta, encoding="utf-8", errors="replace")
        sec = cp["General"] if "General" in cp else {}
        modid_raw = sec.get("modid", "").strip()
        modid = int(modid_raw) if modid_raw.isdigit() and int(modid_raw) > 0 else None
        version = sec.get("version", "").strip() or "local"
        return modid, version
    except Exception:
        return None, "local"


def package_mod(mod_dir: Path, archive_path: Path) -> tuple[str, int]:
    """Zip mod_dir into archive_path. Returns (md5_hex, file_count).

    If `manifest.json` sits directly at `mod_dir/manifest.json`, wrap all files
    under `<mod_dir.name>/` so SMAPI sees a dedicated folder under `Mods/`.
    """
    direct_manifest = any(
        p.is_file() and p.name.lower() == "manifest.json"
        for p in mod_dir.iterdir()
    )
    prefix = mod_dir.name if direct_manifest else ""
    count = 0
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for root, dirs, files in os.walk(mod_dir):
            dirs.sort()
            files.sort()
            rel_root = Path(root).relative_to(mod_dir)
            for fname in files:
                if rel_root == Path(".") and fname.lower() == "meta.ini":
                    continue
                src = Path(root) / fname
                if not src.is_file():
                    continue
                rel = rel_root / fname
                arcname = (Path(prefix) / rel).as_posix() if prefix else rel.as_posix()
                zf.write(src, arcname)
                count += 1

    h = hashlib.md5()
    with archive_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest(), count


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fluorine-dir", required=True, type=Path)
    ap.add_argument("--profile", default="Default")
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--archives-dir", required=True, type=Path)
    ap.add_argument("--out-manifest", required=True, type=Path)
    args = ap.parse_args()

    modlist_path = args.fluorine_dir / "profiles" / args.profile / "modlist.txt"
    mods_root = args.fluorine_dir / "mods"
    args.archives_dir.mkdir(parents=True, exist_ok=True)
    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)

    raw_lines = modlist_path.read_text(encoding="utf-8").splitlines()
    enabled_mods: list[str] = []
    for line in reversed(raw_lines):
        if not line.startswith("+"):
            continue
        name = line[1:]
        if name.endswith("_separator"):
            continue
        enabled_mods.append(name)

    lines = [
        "# Auto-imported from Fluorine Stardew Valley instance",
        "[game]",
        'kind = "stardew"',
        f"pristine = {toml_str(args.pristine)}",
        f"instance = {toml_str(args.instance)}",
        'version = "1.6.15"',
        "",
    ]

    used_slugs: dict[str, int] = {}
    imported = 0
    skipped = 0

    for name in enabled_mods:
        mod_dir = mods_root / name
        if not mod_dir.is_dir():
            skipped += 1
            continue
        base_slug = slugify(name)
        idx = used_slugs.get(base_slug, 0)
        used_slugs[base_slug] = idx + 1
        slug = f"{base_slug}_{idx}" if idx else base_slug
        archive_path = args.archives_dir / f"{slug}.zip"

        md5_hex, file_count = package_mod(mod_dir, archive_path)
        if file_count == 0:
            archive_path.unlink(missing_ok=True)
            skipped += 1
            continue

        modid, version = read_meta_ini(mod_dir)
        lines.append("[[mod]]")
        lines.append(f"name = {toml_str(name)}")
        lines.append(f"version = {toml_str(version)}")
        lines.append(f"url = {toml_str('file://' + str(archive_path.resolve()))}")
        lines.append(f"md5 = {toml_str(md5_hex)}")
        if modid is not None:
            lines.append(f"nexus_mod_id = {modid}")
        lines.append("enabled = true")
        lines.append("")
        imported += 1

    args.out_manifest.write_text("\n".join(lines), encoding="utf-8")
    print(f"Imported {imported} mods (skipped {skipped}) -> {args.out_manifest}")


if __name__ == "__main__":
    main()
