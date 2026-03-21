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
    """Expand user/project shorthand to full GitHub URL."""
    import re
    if re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", repo):
        return f"https://github.com/{repo}"
    return repo


def refresh_credentials(slot: str) -> None:
    host_creds = Path.home() / ".claude" / ".credentials.json"
    slot_creds = paths.run_dir() / slot / ".claude" / ".credentials.json"
    if host_creds.exists() and slot_creds.parent.exists():
        shutil.copy2(host_creds, slot_creds)


def env_args() -> list[str]:
    cfg = config.load()
    pat = cfg.pat()
    if pat:
        return ["--env", f"GH_TOKEN={pat}"]
    return []


def container_name(slot: str) -> str:
    return f"clankr-{slot}"


def is_running(slot: str) -> bool:
    r = subprocess.run(
        ["docker", "inspect", container_name(slot)], capture_output=True
    )
    return r.returncode == 0


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
    dirty = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True
    )
    unpushed = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline", "@{u}..HEAD"],
        capture_output=True, text=True
    )
    d = len(dirty.stdout.strip().splitlines()) if dirty.stdout.strip() else 0
    u = len(unpushed.stdout.strip().splitlines()) if unpushed.stdout.strip() else 0
    return d, u
