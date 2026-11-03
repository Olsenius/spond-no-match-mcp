"""Settings for the gateway's settings page.

Environment variables always win and show as locked. Everything else is stored in
DATA_DIR/settings.json (mode 0600). Without a DATA_DIR directory, saved settings
are kept in memory only.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

VERSION = "1.1.0"

logger = logging.getLogger("spond-mcp")

FIELDS = [
    {
        "key": "SPOND_USERNAME",
        "label": "Spond e-mail",
        "type": "text",
        "required": True,
        "help": "The e-mail you log in to Spond with.",
    },
    {
        "key": "SPOND_PASSWORD",
        "label": "Spond password",
        "type": "secret",
        "required": True,
        "help": "Stored on the server and never shown again.",
    },
    {
        "key": "KIDS_CONFIG",
        "label": "Kids",
        "type": "text",
        "required": False,
        "help": "Optional first names, comma separated, to limit the kids. "
        "Empty = every kid the account is a guardian for.",
    },
    {
        "key": "MCP_READ_ONLY",
        "label": "Read-only",
        "type": "bool",
        "required": False,
        "help": "Hides the tool that answers events.",
    },
]
KEYS = [f["key"] for f in FIELDS]
TYPES = {f["key"]: f["type"] for f in FIELDS}


def parse_bool(name: str, value: str) -> bool:
    v = value.strip().lower()
    if v in ("", "0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    raise ValueError(f"{name} must be a boolean")


def parse_kids(value: str) -> list[str]:
    """First names, comma separated, or a JSON list (also the old [{"name": ...}] format)."""
    v = value.strip()
    if not v:
        return []
    if v.startswith("["):
        try:
            data = json.loads(v)
        except json.JSONDecodeError:
            raise ValueError("KIDS_CONFIG must be first names separated by commas, or a JSON list") from None
        if not isinstance(data, list):
            raise ValueError("KIDS_CONFIG must be first names separated by commas, or a JSON list")
        names = [d.get("name", "") if isinstance(d, dict) else str(d) for d in data]
    else:
        names = v.split(",")
    return [n.strip() for n in names if n.strip()]


def validate(key: str, value: str) -> str:
    if key == "MCP_READ_ONLY":
        return "true" if parse_bool(key, value) else "false"
    if key == "KIDS_CONFIG":
        parse_kids(value)
    return value.strip()


class Settings:
    def __init__(self, env: dict | None = None):
        env = os.environ if env is None else env
        # A variable that is set and not empty is locked.
        self._env = {k: env[k] for k in KEYS if env.get(k, "").strip()}
        for key, value in self._env.items():
            self._env[key] = validate(key, value)
        data_dir = env.get("DATA_DIR", "/data")
        self._path = Path(data_dir) / "settings.json" if data_dir and Path(data_dir).is_dir() else None
        if self._path is None:
            logger.warning("DATA_DIR %r is not a directory; saved settings are kept in memory only", data_dir)
        self._stored = self._load()

    def _load(self) -> dict[str, str]:
        if self._path is None or not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError) as e:
            logger.warning("Could not read saved settings: %s", type(e).__name__)
            return {}
        return {k: v for k, v in data.items() if k in KEYS and isinstance(v, str)}

    def _save(self, data: dict[str, str]) -> None:
        if self._path is None:
            return
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".settings-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, key: str) -> str:
        return self._env.get(key) or self._stored.get(key, "")

    def locked(self, key: str) -> bool:
        return key in self._env

    @property
    def username(self) -> str:
        return self.get("SPOND_USERNAME")

    @property
    def password(self) -> str:
        return self.get("SPOND_PASSWORD")

    @property
    def kids(self) -> list[str]:
        return parse_kids(self.get("KIDS_CONFIG"))

    @property
    def read_only(self) -> bool:
        return parse_bool("MCP_READ_ONLY", self.get("MCP_READ_ONLY"))

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password)

    def update(self, values: dict, clear: list) -> None:
        """Validate everything first, then store. Raises ValueError on bad input."""
        if not isinstance(values, dict) or not isinstance(clear, list):
            raise ValueError('expected {"values": {...}, "clear": [...]}')
        nxt = dict(self._stored)
        for key, value in values.items():
            self._check_key(key)
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            if TYPES[key] == "secret" and value == "":
                continue  # empty secret = keep the current one
            value = validate(key, value)
            if value:
                nxt[key] = value
            else:
                nxt.pop(key, None)
        for key in clear:
            self._check_key(key)
            nxt.pop(key, None)
        self._save(nxt)
        self._stored = nxt

    def _check_key(self, key) -> None:
        if key not in KEYS:
            raise ValueError(f"unknown setting {key!r}")
        if self.locked(key):
            raise ValueError(f"{key} is set by an environment variable and cannot be changed here")

    def doc(self) -> dict:
        fields = []
        for f in FIELDS:
            key = f["key"]
            value = self.get(key)
            field = {**f, "set": bool(value), "locked": self.locked(key)}
            if f["type"] == "secret":
                field["value"] = ""
            elif f["type"] == "bool":
                field["value"] = "true" if self.read_only else "false"
                field["set"] = self.locked(key) or key in self._stored
            else:
                field["value"] = value
            fields.append(field)
        return {"name": "spond-mcp", "version": VERSION, "configured": self.configured, "fields": fields}
