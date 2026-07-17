from __future__ import annotations

import os
import re
from ast import literal_eval
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'} and value[-1:] == value[0]:
        try:
            parsed = literal_eval(value)
            return parsed if isinstance(parsed, str) else str(parsed)
        except (SyntaxError, ValueError):
            return value[1:-1]
    return value


def load_pwd_dotenv(
    dotenv_path: Path | None = None,
    *,
    override: bool = False,
) -> Path | None:
    """Load env vars from the user's current working directory."""
    path = dotenv_path or (Path.cwd() / ".env")
    if not path.is_file():
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()
        if "=" not in stripped:
            continue

        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not _KEY_RE.match(key):
            continue
        if key in os.environ and not override:
            continue
        os.environ[key] = _parse_value(raw_value)

    return path
