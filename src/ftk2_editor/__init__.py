"""FTK2 save file parser and editor.

For The King II stores saves as UTF-8 text with a UTF-8 BOM, then
XOR-obfuscates each Unicode character with the repeating key from
``SaveGameHelper`` in ``FTK2.dll`` (``encryptString = "21398xa2"``).

Under the obfuscation the payload is indented System.Text.Json JSON
for ``UserData`` (``User.ftk2``) or a ``//**summary**//\\n`` +
``GameRunData`` JSON stream (``GameRuns/*.ftk2``).

See ``decompiled/FORMAT.md`` and ``decompiled/SaveGameHelper.cs``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


# Key from SaveGameHelper.encryptString in FTK2.dll
ENCRYPT_KEY = "21398xa2"

FTK2_BOM = b"\xef\xbb\xbf"

FTK2_GAME_DIR = (
    Path.home()
    / ".local/share/Steam/steamapps/compatdata/1676840/pfx/drive_c"
    / "users/steamuser/AppData/LocalLow/IronOak Games/For The King II"
)
USER_SAVE = FTK2_GAME_DIR / "User.ftk2"
BACKUPS_DIR = FTK2_GAME_DIR / "Backups"
GAME_RUNS_DIR = FTK2_GAME_DIR / "GameRuns"


def xor_crypt(text: str, key: str = ENCRYPT_KEY) -> str:
    """XOR each character with the repeating key (encrypt == decrypt)."""
    if not key:
        raise ValueError("encrypt key must be non-empty")
    kl = len(key)
    return "".join(chr(ord(ch) ^ ord(key[i % kl])) for i, ch in enumerate(text))


def decrypt_ftk2_bytes(data: bytes, key: str = ENCRYPT_KEY) -> str:
    """Decrypt a ``.ftk2`` file body to plaintext (usually JSON)."""
    if data.startswith(FTK2_BOM):
        data = data[3:]
    return xor_crypt(data.decode("utf-8"), key)


def encrypt_ftk2_text(text: str, key: str = ENCRYPT_KEY, *, with_bom: bool = True) -> bytes:
    """Encrypt plaintext to a ``.ftk2`` byte payload (UTF-8, optional BOM)."""
    encrypted = xor_crypt(text, key)
    body = encrypted.encode("utf-8")
    return (FTK2_BOM + body) if with_bom else body


def load_user_json(data: bytes, key: str = ENCRYPT_KEY) -> dict[str, Any]:
    """Decrypt ``User.ftk2`` bytes and parse JSON into a dict."""
    plain = decrypt_ftk2_bytes(data, key)
    return json.loads(plain)


def dump_user_json(obj: dict[str, Any], *, indent: int = 2) -> str:
    """Serialize a UserData-like dict the way the game tends to write it."""
    # Game uses JsonHelper with indented JSON and \\r\\n on Windows/Proton.
    return json.dumps(obj, indent=indent, ensure_ascii=False) + "\n"


def parse_ftk2(data: bytes) -> dict[str, Any]:
    """Decrypt and parse a save; returns metadata plus JSON object when possible."""
    has_bom = data.startswith(FTK2_BOM)
    plain = decrypt_ftk2_bytes(data)
    stripped = plain.lstrip()
    result: dict[str, Any] = {
        "header": {
            "has_bom": has_bom,
            "format": "xor-json",
            "encrypt_key": ENCRYPT_KEY,
            "plaintext_prefix": plain[:80],
        },
        "file_size": len(data),
        "plaintext_size": len(plain),
        "json": None,
        "summary": None,
        "run_json_text": None,
        "parse_error": None,
    }

    if stripped.startswith("//**"):
        # GameRuns/*.ftk2: //**{summary}**//\\n{GameRunData...}
        end = plain.find("**//")
        if end != -1:
            summary_raw = plain[4:end]
            rest_start = end + 4
            if rest_start < len(plain) and plain[rest_start] == "\n":
                rest_start += 1
            elif rest_start + 1 < len(plain) and plain[rest_start : rest_start + 2] == "\r\n":
                rest_start += 2
            try:
                result["summary"] = json.loads(summary_raw)
            except json.JSONDecodeError as exc:
                result["parse_error"] = f"summary JSON: {exc}"
            result["run_json_text"] = plain[rest_start:]
            try:
                result["json"] = json.loads(plain[rest_start:])
            except json.JSONDecodeError as exc:
                # Full GameRunData can be huge / nested; keep text available
                if result["parse_error"] is None:
                    result["parse_error"] = f"run JSON: {exc}"
        else:
            result["parse_error"] = "missing **// summary delimiter"
        return result

    try:
        result["json"] = json.loads(plain)
    except json.JSONDecodeError as exc:
        result["parse_error"] = str(exc)
    return result


def dump_summary(result: dict[str, Any]) -> str:
    """Human-readable summary of a parsed save."""
    lines = [
        "=" * 60,
        "FTK2 Save File Summary",
        "=" * 60,
        f"\nFile size: {result.get('file_size', 0)} bytes",
        f"Plaintext size: {result.get('plaintext_size', 0)} bytes",
        f"Format: XOR-obfuscated JSON (key={ENCRYPT_KEY!r})",
        f"Has BOM: {result.get('header', {}).get('has_bom')}",
    ]

    if result.get("parse_error"):
        lines.append(f"Parse note: {result['parse_error']}")

    summary = result.get("summary")
    if isinstance(summary, dict):
        lines.append("\nRun summary:")
        for key in (
            "runID",
            "saveName",
            "difficulty",
            "adventureType",
            "version",
            "dateTime",
        ):
            if key in summary:
                lines.append(f"  {key}: {summary[key]}")

    obj = result.get("json")
    if isinstance(obj, dict):
        lines.append(f"\nTop-level JSON keys ({len(obj)}):")
        for key in sorted(obj.keys()):
            val = obj[key]
            if isinstance(val, dict):
                lines.append(f"  {key}: dict[{len(val)}]")
            elif isinstance(val, list):
                lines.append(f"  {key}: list[{len(val)}]")
            else:
                preview = repr(val)
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(f"  {key}: {preview}")

        local = obj.get("LocalStats")
        if isinstance(local, dict):
            interesting = [
                (k, v)
                for k, v in local.items()
                if any(
                    token in k.upper()
                    for token in ("LORE", "GOLD", "STAT", "UNLOCK", "CURRENCY")
                )
            ][:25]
            if interesting:
                lines.append("\nLocalStats sample (lore/gold/stat-ish):")
                for k, v in interesting:
                    lines.append(f"  {k}: {v}")

        unlocks = obj.get("NewLoreStoreUnlocks")
        if isinstance(unlocks, list):
            lines.append(f"\nNewLoreStoreUnlocks: {len(unlocks)}")
            for item in unlocks[:15]:
                lines.append(f"  - {item}")

    lines.append("")
    return "\n".join(lines)


def edit_field(data: bytes, field_name: str, new_value: str) -> tuple[bytes, bool]:
    """Set a top-level JSON field (or ``LocalStats.<name>``) and re-encrypt.

    ``new_value`` is parsed as JSON when possible (numbers, bools, null);
    otherwise kept as a string.
    """
    plain = decrypt_ftk2_bytes(data)
    if plain.lstrip().startswith("//**"):
        return data, False

    try:
        obj = json.loads(plain)
    except json.JSONDecodeError:
        return data, False

    try:
        parsed_value: Any = json.loads(new_value)
    except json.JSONDecodeError:
        parsed_value = new_value

    if field_name.startswith("LocalStats."):
        stat_key = field_name.split(".", 1)[1]
        stats = obj.setdefault("LocalStats", {})
        if not isinstance(stats, dict):
            return data, False
        stats[stat_key] = parsed_value
    elif field_name in obj or True:
        # Allow creating new top-level keys for experimentation
        obj[field_name] = parsed_value
    else:
        return data, False

    # Preserve original newline style when possible
    if "\r\n" in plain:
        text = json.dumps(obj, indent=2, ensure_ascii=False).replace("\n", "\r\n")
        if plain.endswith("\r\n"):
            text += "\r\n"
        elif plain.endswith("\n"):
            text += "\r\n"
    else:
        text = dump_user_json(obj).rstrip("\n")
        if plain.endswith("\n"):
            text += "\n"

    return encrypt_ftk2_text(text), True


def set_local_stat(data: bytes, stat_name: str, value: int) -> tuple[bytes, bool]:
    """Convenience wrapper for ``LocalStats`` integer edits."""
    return edit_field(data, f"LocalStats.{stat_name}", str(int(value)))


def backup(path: Path | str) -> Path:
    """Copy the save file to a ``.bak`` file and return the backup path."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Save file not found: {src}")

    bak = src.with_suffix(".bak")
    counter = 1
    while bak.exists():
        bak = src.with_suffix(f".bak.{counter}")
        counter += 1

    shutil.copy2(src, bak)
    return bak


def find_save_file(custom_path: str | None = None) -> Path:
    """Locate the FTK2 ``User.ftk2`` file."""
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Save file not found at custom path: {p}")

    if USER_SAVE.exists():
        return USER_SAVE

    if FTK2_GAME_DIR.exists():
        candidate = FTK2_GAME_DIR / "User.ftk2"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Could not locate User.ftk2.  Searched {FTK2_GAME_DIR}.  "
        "Is the game installed under Steam?"
    )


def verify_save(data: bytes) -> dict[str, Any]:
    """Verify BOM + successful decrypt-to-JSON (for User saves)."""
    issues: list[str] = []

    if not data.startswith(FTK2_BOM):
        issues.append("Missing UTF-8 BOM prefix")

    if len(data) < 32:
        issues.append(f"File suspiciously small ({len(data)} bytes)")

    if len(data) > 100_000_000:
        issues.append(f"File suspiciously large ({len(data)} bytes)")

    plain = ""
    looks_json = False
    try:
        plain = decrypt_ftk2_bytes(data)
        stripped = plain.lstrip()
        looks_json = stripped.startswith("{") or stripped.startswith("//**")
        if not looks_json:
            issues.append("Decrypted payload does not look like JSON / GameRun summary")
        elif stripped.startswith("{"):
            json.loads(plain)
    except UnicodeDecodeError:
        issues.append("File is not valid UTF-8 after BOM")
    except json.JSONDecodeError as exc:
        issues.append(f"Decrypted JSON failed to parse: {exc}")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "file_size": len(data),
        "has_bom": data.startswith(FTK2_BOM),
        "decrypts_to_json": looks_json,
        "plaintext_prefix": plain[:60] if plain else "",
    }
