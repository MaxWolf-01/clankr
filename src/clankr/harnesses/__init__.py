"""Harness abstraction — each harness knows how to set up and run a specific coding agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


class Harness(Protocol):
    """Interface that each coding agent harness must implement."""

    name: str

    def dockerfile_path(self) -> Path:
        """Path to the Dockerfile for building this harness's image."""
        ...

    def image_name(self) -> str:
        """Docker image name for this harness."""
        ...

    def setup_config_dir(self, config_dir: Path, profile_dir: Path) -> None:
        """Populate the agent's config directory from a profile.

        Copies context files, settings, init scripts, and seeds any
        harness-specific config (onboarding bypass, etc.).
        """
        ...

    def refresh_credentials(self, config_dir: Path) -> None:
        """Copy fresh credentials from the host into the slot's config dir."""
        ...

    def config_mount_args(self, config_dir: Path) -> list[str]:
        """Docker -v args to mount the config dir into the container."""
        ...

    def session_sync_mount_args(self, host_repo_path: str, slot_run_dir: Path) -> list[str]:
        """Docker -v args for session sync between host and container."""
        ...

    def env_args(self, config_dir: Path) -> list[str]:
        """Docker --env args (git identity, tokens, profile-declared env)."""
        ...

    def container_cmd(self, extra_args: list[str]) -> list[str]:
        """The command (ENTRYPOINT args) to pass to docker run."""
        ...

    def encode_host_path(self, path: str) -> str:
        """Encode a host path for session directory naming."""
        ...

    def context_file_name(self) -> str:
        """Primary context file name this harness looks for (e.g. CLAUDE.md, AGENTS.md)."""
        ...

    def fallback_context_file_name(self) -> str:
        """Fallback context file name if the primary isn't found."""
        ...

    def sessions_subdir(self, slot_run_dir: Path) -> Path:
        """Path inside the slot's run dir where sessions are stored (for archival)."""
        ...

    def host_sessions_dir(self, host_repo_path: str) -> Path:
        """Host-side directory where sessions for a given repo path are stored."""
        ...


def common_env_args() -> list[str]:
    """Docker --env args shared by all harnesses: git identity + GH_TOKEN."""
    from clankr import config

    cfg = config.load()
    args: list[str] = []
    pat = cfg.pat()
    if pat:
        args += ["--env", f"GH_TOKEN={pat}"]
    if cfg.clanker_user:
        email = f"{cfg.clanker_user}@users.noreply.github.com"
        args += [
            "--env", f"GIT_AUTHOR_NAME={cfg.clanker_user}",
            "--env", f"GIT_AUTHOR_EMAIL={email}",
            "--env", f"GIT_COMMITTER_NAME={cfg.clanker_user}",
            "--env", f"GIT_COMMITTER_EMAIL={email}",
        ]
    return args


def settings_env_args(settings_path: Path) -> list[str]:
    """Extract the `env` object from a settings.json and format as docker --env args."""
    if not settings_path.exists():
        return []
    env = json.loads(settings_path.read_text()).get("env") or {}
    return [arg for k, v in env.items() for arg in ("--env", f"{k}={v}")]


_HARNESSES: dict[str, Harness] = {}
_loaded = False


def register(harness: Harness) -> None:
    _HARNESSES[harness.name] = harness


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from clankr.harnesses import claude as _claude  # noqa: F811, F401
    from clankr.harnesses import pi as _pi  # noqa: F401


def get(name: str) -> Harness:
    _ensure_loaded()
    if name not in _HARNESSES:
        avail = ", ".join(sorted(_HARNESSES))
        raise ValueError(f"Unknown harness: {name!r}. Available: {avail}")
    return _HARNESSES[name]


def available() -> list[str]:
    _ensure_loaded()
    return sorted(_HARNESSES)
