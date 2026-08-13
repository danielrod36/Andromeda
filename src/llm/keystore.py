"""API-key storage: OS keychain primary, owner-only file fallback (M0.7, D7).

The LLM API key never lives in the settings file. It is stored in the OS
keychain via ``keyring`` (service ``andromeda``); on systems without a
keyring backend (headless Linux, CI), it falls back to an owner-only
(0600) JSON file next to the settings. The client only ever sees a masked
tail (``…1234``) via :func:`masked_tail`.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Protocol

#: Keychain service name (shown in OS keychain UIs).
SERVICE_NAME = "andromeda"

#: Fallback file name inside the settings directory.
KEYS_FILENAME = "llm.keys.json"


class KeyStore(Protocol):
    """Secret storage backend."""

    def get(self, account: str) -> str:
        """Return the stored secret for ``account``, or "" when absent."""
        ...

    def set(self, account: str, secret: str) -> None:
        """Store ``secret`` for ``account``."""
        ...

    def delete(self, account: str) -> None:
        """Remove any secret for ``account``."""
        ...

    @property
    def backend_name(self) -> str:
        """``"keyring"`` or ``"file"`` — surfaced in Settings (D7 visible status)."""
        ...


class KeyringStore:
    """OS keychain backend via the ``keyring`` package."""

    def __init__(self) -> None:
        import keyring

        self._keyring = keyring

    @classmethod
    def available(cls) -> bool:
        """True when a real keyring backend is usable on this system."""
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring

            backend = keyring.get_keyring()
            return not isinstance(backend, FailKeyring)
        except Exception:
            return False

    def get(self, account: str) -> str:
        return self._keyring.get_password(SERVICE_NAME, account) or ""

    def set(self, account: str, secret: str) -> None:
        self._keyring.set_password(SERVICE_NAME, account, secret)

    def delete(self, account: str) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self._keyring.delete_password(SERVICE_NAME, account)

    @property
    def backend_name(self) -> str:
        return "keyring"


class FileKeyStore:
    """Owner-only JSON file fallback (headless systems without a keychain)."""

    def __init__(self, settings_dir: str | Path) -> None:
        self._path = Path(settings_dir) / KEYS_FILENAME

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        # Clean up a stale tmp file left by a previous crash.
        with contextlib.suppress(OSError):
            tmp.unlink()
        content = json.dumps(data, indent=2)
        # Create the file with 0o600 from the start so the secret is never
        # written at default umask (0644) before chmod catches up.
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        os.replace(tmp, self._path)

    def get(self, account: str) -> str:
        return self._read().get(account, "")

    def set(self, account: str, secret: str) -> None:
        data = self._read()
        data[account] = secret
        self._write(data)

    def delete(self, account: str) -> None:
        data = self._read()
        if account in data:
            del data[account]
            self._write(data)

    @property
    def backend_name(self) -> str:
        return "file"


def get_keystore(settings_dir: str | Path) -> KeyStore:
    """Return the OS keychain when usable, else the owner-only file store.

    On some headless systems ``keyring.get_keyring()`` returns a backend that
    reports as available but raises on actual use (e.g. ``ChainerBackend``
    with no working backend underneath). To avoid crashes we probe the
    keyring with a harmless read before committing to it.
    """
    if KeyringStore.available():
        try:
            store = KeyringStore()
            store._keyring.get_password(SERVICE_NAME, "__andromeda_test__")
            return store
        except Exception:
            pass  # fall through to file backend
    return FileKeyStore(settings_dir)


def masked_tail(secret: str) -> str:
    """The only key material the client ever sees: ``…last4`` (D7)."""
    if not secret:
        return ""
    if len(secret) <= 4:
        return "…"
    return f"…{secret[-4:]}"
