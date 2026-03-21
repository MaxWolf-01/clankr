"""Config file management."""

from dataclasses import dataclass, field
from pathlib import Path

from clankr.paths import config_file


@dataclass
class Config:
    github_user: str = ""
    """Your GitHub username (repo owner)."""
    clanker_user: str = ""
    """Bot GitHub account username."""
    pat_file: str = ""
    """Path to file containing the GitHub PAT (one line, just the token)."""

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
    ]
    path.write_text("\n".join(lines) + "\n")
