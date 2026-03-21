"""XDG-compliant paths for clankr config and data."""

from pathlib import Path
import os


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "clankr"


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "clankr"


def repos_dir() -> Path:
    return data_dir() / "repos"


def run_dir() -> Path:
    return data_dir() / "run"


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def config_file() -> Path:
    return config_dir() / "config.toml"


def dockerfile_path() -> Path:
    """User override, or bundled default."""
    user = config_dir() / "Dockerfile"
    if user.exists():
        return user
    return Path(__file__).parent / "Dockerfile"
