"""Docker container management."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from clankr import paths

if TYPE_CHECKING:
    from clankr.harnesses import Harness


def build_image(harness: Harness) -> None:
    from datetime import date

    dockerfile = harness.dockerfile_path()
    subprocess.run(
        [
            "docker", "build", "-q", "-t", harness.image_name(),
            "-f", str(dockerfile), str(dockerfile.parent),
            "--build-arg", f"AGENT_CACHEBUST={date.today()}",
        ],
        stdout=subprocess.DEVNULL,
        check=True,
    )


def resolve_profile_dir(profile: str) -> Path:
    """Resolve a profile name or path to a directory. Exits if not found."""
    if "/" in profile:
        profile_dir = Path(profile).expanduser().resolve()
    else:
        profile_dir = paths.profiles_dir() / profile
    if not profile_dir.exists():
        available = [p.name for p in paths.profiles_dir().iterdir() if p.is_dir()]
        print(f"Profile not found: {profile}", file=sys.stderr)
        print(f"Available: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)
    return profile_dir


def setup_slot(slot: str, profile: str, harness: Harness) -> Path:
    """Set up a slot's config dir from a profile. Returns the config dir path."""
    config_dir = paths.run_dir() / slot / "config"
    profile_dir = resolve_profile_dir(profile)

    harness.setup_config_dir(config_dir, profile_dir)

    (paths.run_dir() / slot / "profile").write_text(profile)
    (paths.run_dir() / slot / "harness").write_text(harness.name)

    return config_dir


def profile_mounts(profile: str) -> list[str]:
    """Parse profile mounts file into docker -v args."""
    profile_dir = resolve_profile_dir(profile)
    mounts_file = profile_dir / "mounts"
    if not mounts_file.exists():
        return []
    args = []
    for line in mounts_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) < 2:
            print(f"Invalid mount spec (need src:dest): {line}", file=sys.stderr)
            sys.exit(1)
        src, dest = parts[0], parts[1]
        mode = parts[2] if len(parts) > 2 else "rw"
        if src.startswith("./"):
            src = str(profile_dir / src[2:])
        else:
            src = str(Path(src).expanduser().resolve())
        args.extend(["-v", f"{src}:{dest}:{mode}"])
    return args


def clone_repo(repo_url: str, slot: str) -> Path:
    repo_dir = paths.repos_dir() / slot
    if repo_dir.exists():
        return repo_dir
    print(f"Cloning {repo_url} → {repo_dir}", file=sys.stderr)
    paths.repos_dir().mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", repo_url, str(repo_dir)], check=True)
    return repo_dir


def expand_repo_url(repo: str) -> str:
    """Expand repo argument to a cloneable URL or local path.

    Resolution order:
    1. Explicit URL (https://, git@, ssh://) → used as-is
    2. Local path (exists on disk)           → resolved to absolute path
    3. user/project shorthand                → https://github.com/user/project
    4. Otherwise                             → error
    """
    import re

    if repo.startswith(("https://", "http://", "git@", "ssh://")):
        return repo
    local = Path(repo).expanduser().resolve()
    if local.exists():
        return str(local)
    if re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", repo):
        return f"https://github.com/{repo}"
    print(f"Error: unrecognized repo: {repo!r}", file=sys.stderr)
    print("  Expected: user/project, a URL, or a local path", file=sys.stderr)
    sys.exit(1)


def refresh_credentials(slot: str, harness: Harness) -> None:
    config_dir = slot_config_dir(slot)
    if config_dir.exists():
        harness.refresh_credentials(config_dir)


def slot_config_dir(slot: str) -> Path:
    """Return the config dir for a slot. Migrates legacy .claude layout on first access."""
    config = paths.run_dir() / slot / "config"
    legacy = paths.run_dir() / slot / ".claude"
    if not config.exists() and legacy.exists():
        legacy.rename(config)
    return config


def slot_harness_name(slot: str) -> str:
    harness_file = paths.run_dir() / slot / "harness"
    if harness_file.exists():
        return harness_file.read_text().strip()
    return "claude"


def container_name(slot: str) -> str:
    return f"clankr-{slot}"


def container_state(slot: str) -> str | None:
    """Return container state ('running', 'exited', etc.) or None if not found."""
    name = container_name(slot)
    r = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", name],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def remove_container(slot: str) -> None:
    subprocess.run(["docker", "rm", "-f", container_name(slot)], capture_output=True)


def next_slot(base: str) -> str:
    """Find the next available slot name: base-1, base-2, etc.

    Cleans up stale (non-running) containers along the way.
    """
    n = 1
    while True:
        candidate = f"{base}-{n}"
        state = container_state(candidate)
        if state is None:
            # No container — also check if slot dir exists but container is gone
            slot_dir = paths.run_dir() / candidate
            if not slot_dir.exists():
                return candidate
            # Slot dir exists but no container — reusable
            return candidate
        if state == "running":
            n += 1
            continue
        # Stale container — clean it up, reuse the slot
        remove_container(candidate)
        return candidate


def is_running(slot: str) -> bool:
    return container_state(slot) == "running"


def slot_status(slot: str) -> str:
    name = container_name(slot)
    if not is_running(slot):
        return "stopped"
    r = subprocess.run(["tmux", "has-session", "-t", name], capture_output=True)
    if r.returncode == 0:
        return "detached"
    return "running"


def slot_profile(slot: str) -> str:
    profile_file = paths.run_dir() / slot / "profile"
    if profile_file.exists():
        return profile_file.read_text().strip()
    return "bare"


def sync_mount_args(host_repo_path: str, slot: str, harness: Harness) -> list[str]:
    """Return docker -v args for session sync bind mount."""
    slot_run_dir = paths.run_dir() / slot
    return harness.session_sync_mount_args(host_repo_path, slot_run_dir)


def save_sync_target(slot: str, host_path: str) -> None:
    """Record the sync target for a slot."""
    target_file = paths.run_dir() / slot / "sync_target"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(host_path + "\n")


def get_sync_target(slot: str) -> str | None:
    """Get the sync target for a slot, if any."""
    f = paths.run_dir() / slot / "sync_target"
    if f.exists():
        return f.read_text().strip()
    return None


def clear_sync_target(slot: str) -> None:
    """Remove stale sync_target from a previous launch."""
    f = paths.run_dir() / slot / "sync_target"
    if f.exists():
        f.unlink()


def archive_sessions(slot: str, harness: Harness) -> int:
    """Archive session files from a slot. Returns count.

    Skips if sync was active (sessions already on host via bind mount).
    """
    if get_sync_target(slot):
        return 0

    slot_run_dir = paths.run_dir() / slot
    sessions_dir = harness.sessions_subdir(slot_run_dir)
    if not sessions_dir.exists():
        return 0

    dest_dir = paths.sessions_dir() / slot
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for item in sessions_dir.iterdir():
        if item.name == "memory":
            continue
        dest = dest_dir / item.name
        if item.is_file() and item.suffix == ".jsonl":
            shutil.copy2(item, dest)
            copied += 1
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
    return copied


def migrate_sessions_to_sync(slot: str, host_repo_path: str, harness: Harness) -> int:
    """Copy existing session files from a slot to the sync target. For retroactive sync."""
    slot_run_dir = paths.run_dir() / slot
    sessions_dir = harness.sessions_subdir(slot_run_dir)
    if not sessions_dir.exists():
        return 0

    dest_dir = harness.host_sessions_dir(host_repo_path)
    dest_dir.mkdir(parents=True, exist_ok=True)

    migrated = 0
    for item in sessions_dir.iterdir():
        if item.name == "memory":
            continue
        dest = dest_dir / item.name
        if item.is_file() and item.suffix == ".jsonl":
            shutil.copy2(item, dest)
            migrated += 1
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
    return migrated


def git_status(slot: str) -> tuple[int, int]:
    """Returns (uncommitted, unpushed) counts."""
    repo = paths.repos_dir() / slot
    if not repo.exists():
        return 0, 0
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True)
    unpushed = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline", "@{u}..HEAD"], capture_output=True, text=True
    )
    d = len(dirty.stdout.strip().splitlines()) if dirty.stdout.strip() else 0
    u = len(unpushed.stdout.strip().splitlines()) if unpushed.stdout.strip() else 0
    return d, u
