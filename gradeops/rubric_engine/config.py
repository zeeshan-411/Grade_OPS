"""Environment / model configuration for the grading pipeline."""
from __future__ import annotations

import os
import re
from pathlib import Path

# Default Gemini model. Override with GEMINI_MODEL env var.
# gemini-2.5-flash-lite has the most generous free-tier quota; bump to
# gemini-2.5-flash / gemini-2.5-pro for stricter grading when the key has quota.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

_ENV_LINE_RE = re.compile(
    r"""^\s*
        (?:export\s+)?
        ([A-Za-z_][A-Za-z0-9_]*)   # key
        \s*=\s*
        (.*?)                       # raw value
        \s*;?\s*$                   # optional trailing semicolon
    """,
    re.VERBOSE,
)


def _find_env_file(start: Path | None = None) -> Path | None:
    """Walk up from the working directory looking for a .env file."""
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        env = candidate / ".env"
        if env.is_file():
            return env
    return None


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_env(path: str | Path | None = None, override: bool = False) -> dict[str, str]:
    """Lightweight .env loader.

    Accepts the user's `KEY = 'value';` format (spaces around `=`, trailing semicolon,
    single-or-double-quoted values). Does not pull in python-dotenv at import time
    so the import graph stays light.

    Returns a dict of the keys it loaded into the environment.
    """
    if path is None:
        env_file = _find_env_file()
    else:
        env_file = Path(path)
        if not env_file.is_file():
            env_file = None

    loaded: dict[str, str] = {}
    if env_file is None:
        return loaded

    try:
        env_text = env_file.read_text(encoding="utf-8")
    except (OSError, TimeoutError) as exc:
        # iCloud "dataless" files or transient endpoint-security throttling can
        # cause read_text to time out. Don't block process startup — fall back
        # to whatever the shell already injected into os.environ.
        import logging

        logging.getLogger(__name__).warning(
            "Could not read %s (%s); proceeding with shell env only.", env_file, exc
        )
        return loaded

    for raw_line in env_text.splitlines():
        line = raw_line.split("#", 1)[0]
        if not line.strip():
            continue
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        key, raw_value = match.group(1), match.group(2)
        value = _strip_quotes(raw_value)
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value

    return loaded
