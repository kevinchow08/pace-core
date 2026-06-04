"""
Push notifications via Ntfy (v0).

To swap to Expo Push (Phase 2): replace _send_ntfy with _send_expo,
keep the public push() signature identical — zero changes to callers.
"""
import httpx

from src.config import settings


def push(title: str, body: str) -> None:
    _send_ntfy(title, body)


def _send_ntfy(title: str, body: str) -> None:
    httpx.post(
        f"https://ntfy.sh/{settings.ntfy_topic}",
        content=body.encode(),
        headers={"Title": title},
        timeout=10,
    )
