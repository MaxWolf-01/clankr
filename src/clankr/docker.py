"""Docker container management."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from clankr import config, paths

IMAGE_NAME = "clankr-agent"


def build_image() -> None:
    dockerfile = paths.dockerfile_path()
    subprocess.run(
        ["docker", "build", "-q", "-t", IMAGE_NAME, "-f", str(dockerfile), str(dockerfile.parent)],
        stdout=subprocess.DEVNULL,
        check=True,
    )


def setup_slot(slot: str, profile: str) -> Path:
    """Set up a slot's .claude/ dir from a profile. Returns the claude dir path."""
    claude_dir = paths.run_dir() / slot / ".claude"
    if (claude_dir / "CLAUDE.md").exists():
        return claude_dir

    profile_dir = paths.profiles_dir() / profile
    if not profile_dir.exists():
        available = [p.name for p in paths.profiles_dir().iterdir() if p.is_dir()]
        print(f"Profile not found: {profile}")
        print(f"Available: {', '.join(available)}")
        sys.exit(1)

    print(f"Setting up profile: {profile}")
    claude_dir.mkdir(parents=True, exist_ok=True)

    # Copy credentials from host
    host_creds = Path.home() / ".claude" / ".credentials.json"
    if host_creds.exists():
        shutil.copy2(host_creds, claude_dir / ".credentials.json")

    # Seed .claude.json for TUI onboarding bypass
    (claude_dir / ".claude.json").write_text(
        json.dumps({"hasCompletedOnboarding": True, "installMethod": "npm", "numStartups": 5})
    )

    # Run profile setup script
    setup_script = profile_dir / "setup"
    if setup_script.exists():
        subprocess.run(["bash", str(setup_script), str(claude_dir)], check=True)

    # Copy CLAUDE.md + settings.json (after setup, so ours wins)
    for f in ["CLAUDE.md", "settings.json"]:
        src = profile_dir / f
        if src.exists():
            shutil.copy2(src, claude_dir / f)

    return claude_dir


def clone_repo(repo_url: str, slot: str) -> Path:
    repo_dir = paths.repos_dir() / slot
    if repo_dir.exists():
        return repo_dir
    print(f"Cloning {repo_url} → {repo_dir}")
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
    print(f"Error: unrecognized repo: {repo!r}")
    print("  Expected: user/project, a URL, or a local path")
    sys.exit(1)


def refresh_credentials(slot: str) -> None:
    host_creds = Path.home() / ".claude" / ".credentials.json"
    slot_creds = paths.run_dir() / slot / ".claude" / ".credentials.json"
    if host_creds.exists() and slot_creds.parent.exists():
        shutil.copy2(host_creds, slot_creds)


def env_args() -> list[str]:
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
    gsd_dir = paths.run_dir() / slot / ".claude" / "get-shit-done"
    return "gsd" if gsd_dir.exists() else "bare"


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
