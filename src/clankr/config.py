"""Config file management."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from clankr.paths import config_file, sync_map_file


@dataclass
class Config:
    github_user: str = ""
    """Your GitHub username (repo owner)."""
    clanker_user: str = ""
    """Bot GitHub account username."""
    pat_file: str = ""
    """Path to file containing the GitHub PAT (one line, just the token)."""
    save_sessions: str = "true"
    """Auto-archive sessions on rm/clean. Set to "false" to disable."""
    default_harness: str = "claude"
    """Default agent harness (claude, pi)."""

    def pat(self) -> str | None:
        if not self.pat_file:
            return None
        p = Path(self.pat_file).expanduser()
        if p.exists():
            return p.read_text().strip()
        return None


def load() -> Config:
    path = config_file()
    if not path.exists():
        return Config()
    cfg = Config()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if hasattr(cfg, key):
                setattr(cfg, key, val)
    return cfg


def save(cfg: Config) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'github_user = "{cfg.github_user}"',
        f'clanker_user = "{cfg.clanker_user}"',
        f'pat_file = "{cfg.pat_file}"',
        f'save_sessions = "{cfg.save_sessions}"',
        f'default_harness = "{cfg.default_harness}"',
    ]
    path.write_text("\n".join(lines) + "\n")


def load_sync_map() -> dict[str, str]:
    path = sync_map_file()
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_sync_map(mapping: dict[str, str]) -> None:
    path = sync_map_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2) + "\n")


def normalize_repo(repo: str) -> str | None:
    """Extract user/project from various repo formats. Returns None for local paths."""
    if Path(repo).expanduser().resolve().exists():
        return None
    for prefix in [
        "https://github.com/",
        "http://github.com/",
        "git@github.com:",
        "ssh://git@github.com/",
    ]:
        if repo.startswith(prefix):
            repo = repo[len(prefix) :]
            break
    repo = repo.removesuffix(".git").strip("/")
    if re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", repo):
        return repo
    return None
