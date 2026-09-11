"""Command-line interface for the FTK2 save editor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ftk2_editor import (
    backup,
    decrypt_ftk2_bytes,
    dump_summary,
    edit_field,
    encrypt_ftk2_text,
    find_save_file,
    parse_ftk2,
    rename_party_member_synced,
    verify_save,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ftk2-edit",
        description="Read and edit For The King II (FTK2) save files (XOR-encrypted JSON).",
    )
    parser.add_argument(
        "save_file",
        nargs="?",
        default=None,
        help="Path to User.ftk2 / GameRuns/*.ftk2 (default: auto-locate User.ftk2)",
    )
    parser.add_argument("--info", action="store_true", help="Print save summary")
    parser.add_argument("--dump", action="store_true", help="Dump parsed JSON summary")
    parser.add_argument(
        "--decrypt",
        metavar="PATH",
        help="Write decrypted plaintext JSON to PATH",
    )
    parser.add_argument(
        "--encrypt-from",
        metavar="PATH",
        help="Encrypt plaintext JSON from PATH into the save (use with --output)",
    )
    parser.add_argument(
        "--set",
        metavar="FIELD=VALUE",
        action="append",
        dest="updates",
        help="Set a top-level JSON field or LocalStats.NAME (e.g. --set LocalStats.LANG_ID=1)",
    )
    parser.add_argument(
        "--rename",
        metavar="ID=NEWNAME",
        action="append",
        dest="renames",
        help="Rename a party character: --rename <GUID-or-current-name>=<New Name> "
        "(uses GameRuns Entities or User PartyCharacters)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a .bak backup before edits (default: backup)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify decrypt/JSON shape",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Output path for edited/encrypted save (default: overwrite input)",
    )

    args = parser.parse_args()
    save_path = Path(args.save_file) if args.save_file else find_save_file()

    if args.encrypt_from:
        src = Path(args.encrypt_from)
        if not src.exists():
            print(f"Error: plaintext file not found: {src}", file=sys.stderr)
            sys.exit(1)
        text = src.read_text(encoding="utf-8")
        # Validate JSON when it is a User save (not GameRun summary form)
        if not text.lstrip().startswith("//**"):
            json.loads(text)
        out = Path(args.output) if args.output else save_path
        if not args.no_backup and out.exists():
            print(f"Backup created: {backup(out)}")
        out.write_bytes(encrypt_ftk2_text(text))
        print(f"Encrypted {src} -> {out}")
        sys.exit(0)

    if not save_path.exists():
        print(f"Error: Save file not found at {save_path}", file=sys.stderr)
        sys.exit(1)

    data = save_path.read_bytes()
    verification = verify_save(data)
    if not verification["valid"]:
        print("Warning: Save file verification reported issues:", file=sys.stderr)
        for issue in verification["issues"]:
            print(f"  - {issue}", file=sys.stderr)

    if args.verify_only:
        print(f"Save file: {save_path}")
        print(f"Size: {verification['file_size']} bytes")
        print(f"Has BOM: {verification['has_bom']}")
        print(f"Decrypts to JSON-like: {verification['decrypts_to_json']}")
        print(f"Plaintext prefix: {verification['plaintext_prefix']!r}")
        if verification["issues"]:
            print("Issues:")
            for issue in verification["issues"]:
                print(f"  - {issue}")
            sys.exit(1)
        print("All checks passed.")
        sys.exit(0)

    if args.decrypt:
        plain = decrypt_ftk2_bytes(data)
        out = Path(args.decrypt)
        out.write_text(plain, encoding="utf-8")
        print(f"Decrypted {save_path} -> {out} ({len(plain)} chars)")
        sys.exit(0)

    if args.info or args.dump or not (args.updates or args.renames):
        print(f"Save file: {save_path}")
        print(f"Size: {verification['file_size']} bytes")
        print(dump_summary(parse_ftk2(data)))
        if not (args.updates or args.renames):
            sys.exit(0)

    if not args.no_backup:
        print(f"Backup created: {backup(save_path)}")

    modified = data
    for update in args.updates or []:
        if "=" not in update:
            print(f"Error: Invalid --set '{update}'. Use FIELD=VALUE.", file=sys.stderr)
            sys.exit(1)
        field_name, value = update.split("=", 1)
        modified, success = edit_field(modified, field_name, value)
        if success:
            print(f"  Set {field_name} = {value}")
        else:
            print(f"  Warning: Could not set field '{field_name}'", file=sys.stderr)
            sys.exit(1)

    is_run = decrypt_ftk2_bytes(modified).lstrip().startswith("//**")
    user_path: Path | None = None
    if is_run:
        try:
            candidate = find_save_file()
            if candidate.exists() and candidate != save_path:
                user_path = candidate
        except FileNotFoundError:
            user_path = None

    for rename in args.renames or []:
        if "=" not in rename:
            print(f"Error: Invalid --rename '{rename}'. Use ID=NEWNAME.", file=sys.stderr)
            sys.exit(1)
        identifier, new_name = rename.split("=", 1)
        user_data = user_path.read_bytes() if user_path else None
        modified, success, user_modified = rename_party_member_synced(
            modified, new_name, guid=identifier, user_data=user_data
        )
        if not success:
            modified, success, user_modified = rename_party_member_synced(
                modified, new_name, current_name=identifier, user_data=user_data
            )
        if success:
            print(f"  Renamed {identifier} -> {new_name}")
            if success and user_modified is not None and user_path is not None:
                if not args.no_backup:
                    print(f"  Synced {user_path.name} roster backup: {backup(user_path)}")
                user_path.write_bytes(user_modified)
                print(f"  Synced {user_path.name} PartyCharacters/LastRunCharacters")
        else:
            print(f"  Warning: Could not rename '{identifier}'", file=sys.stderr)
            sys.exit(1)

    output_path = Path(args.output) if args.output else save_path
    if not args.no_backup and output_path == save_path:
        print("\nWARNING: Overwriting live save file. Prefer letting --no-backup be off, or use --output.", file=sys.stderr)
    output_path.write_bytes(modified)
    print(f"  Written to: {output_path}")


if __name__ == "__main__":
    main()
