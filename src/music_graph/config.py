"""Configuration loader for settings.toml, seeds.toml, and .env."""

from pathlib import Path

import tomli
from dotenv import load_dotenv
from loguru import logger


def _find_project_root() -> Path:
    """Walk up from CWD looking for pyproject.toml."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current


PROJECT_ROOT = _find_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"


def load_settings() -> dict:
    """Load config/settings.toml."""
    path = CONFIG_DIR / "settings.toml"
    if not path.exists():
        logger.warning("settings.toml not found at {}", path)
        return {}
    with open(path, "rb") as f:
        return tomli.load(f)


def load_seeds() -> dict:
    """Load config/seeds.toml."""
    path = CONFIG_DIR / "seeds.toml"
    if not path.exists():
        logger.warning("seeds.toml not found at {}", path)
        return {}
    with open(path, "rb") as f:
        return tomli.load(f)


def load_env() -> None:
    """Load .env file from project root."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.debug("Loaded .env from {}", env_path)
    else:
        logger.debug("No .env file found at {}", env_path)


# Load env on import
load_env()
