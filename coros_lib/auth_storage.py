"""
Simple file-based token storage for self-use.

Stores the auth JSON in .coros_token.json at the project root.
No keyring, no encryption — this file should not be committed to git.
"""
import json
import os
from pathlib import Path

_TOKEN_FILE = Path(__file__).parent.parent / ".coros_token.json"


def store_token(token_json: str) -> None:
    _TOKEN_FILE.write_text(token_json, encoding="utf-8")


def get_token() -> str | None:
    if not _TOKEN_FILE.exists():
        return None
    try:
        return _TOKEN_FILE.read_text(encoding="utf-8")
    except Exception:
        return None


def clear_token() -> None:
    _TOKEN_FILE.unlink(missing_ok=True)
