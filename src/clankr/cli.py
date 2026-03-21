"""Run coding agents in isolated Docker containers.

Examples::

    clankr init
    clankr launch user/project
    clankr launch -p gsd user/project
    clankr launch -d -p gsd user/project
    clankr ls
    clankr attach my-project
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import tyro
from tyro.extras import SubcommandApp

from clankr import config, docker, paths

app = SubcommandApp()


@dataclass
class Launch:
    repo: Annotated[str, tyro.conf.Positional]
    """Repository: user/project, https://github.com/user/project, or /local/path."""
    profile: Annotated[str, tyro.conf.arg(aliases=["-p"])] = "bare"
    """Profile to use. See 'clankr profiles ls'."""
    slot: Annotated[str, tyro.conf.arg(aliases=["-s"])] = ""
    """Slot name. Defaults to repo name. Use for multiple agents on the same repo."""
    detach: Annotated[bool, tyro.conf.arg(aliases=["-d"])] = False
    """Run in a tmux session (detached). Reattach with: clankr attach <slot>."""
    claude_args: Annotated[list[str], tyro.conf.Positional, tyro.conf.UseAppendAction] = field(default_factory=list)
    """Extra arguments passed to claude (after --)."""


@app.command(
    name="launch",
)
def launch(args: Launch) -> None:
    """Launch an agent on a repository."""
    repo_url = docker.expand_repo_url(args.repo)
    base = args.slot or Path(repo_url.rstrip("/")).stem.removesuffix(".git")

    if args.slot:
        slot = args.slot
        # Explicit slot: handle stale container
        state = docker.container_state(slot)
        if state == "running":
            print(f"Slot {slot} is already running. Attaching...")
            name = docker.container_name(slot)
            # Check if it's in a tmux session
            r = subprocess.run(["tmux", "has-session", "-t", name], capture_output=True)
            if r.returncode == 0:
                subprocess.run(["tmux", "attach", "-t", name])
            else:
                subprocess.run(["docker", "attach", name])
            return
        elif state is not None:
            docker.remove_container(slot)
    else:
        slot = docker.next_slot(base)

    repo_dir = docker.clone_repo(repo_url, slot)
    claude_dir = docker.setup_slot(slot, args.profile)

    docker.build_image()
    docker.refresh_credentials(slot)

    name = docker.container_name(slot)

    common = [
        "-v",
        f"{repo_dir}:/work",
        "-v",
        f"{claude_dir}:/home/agent/.claude",
        *docker.env_args(),
    ]

    print(f"Launching {name} (profile: {args.profile})")

    if args.detach:
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
        cmd = f"docker run --rm -it --name {name} {' '.join(common)} {docker.IMAGE_NAME} {' '.join(args.claude_args)}"
        subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                name,
                "-x",
                str(shutil.get_terminal_size().columns),
                "-y",
                str(shutil.get_terminal_size().lines),
                cmd,
            ]
        )
        print(f"Detached: tmux session '{name}'")
        print(f"  attach:  clankr attach {slot}")
        print("  detach:  Ctrl+B D")
    else:
        subprocess.run(
            ["docker", "run", "--rm", "-it", "--name", name, *common, docker.IMAGE_NAME, *args.claude_args],
        )


@app.command(name="ls")
def list_slots() -> None:
    """List all slots."""
    run = paths.run_dir()
    if not run.exists():
        print("no slots")
        return
    slots = [d.name for d in sorted(run.iterdir()) if d.is_dir()]
    if not slots:
        print("no slots")
        return
    print(f"{'SLOT':<20} {'PROFILE':<8} {'STATUS':<12} REPO")
    for s in slots:
        profile = docker.slot_profile(s)
        status = docker.slot_status(s)
        repo = paths.repos_dir() / s
        print(f"{s:<20} {profile:<8} {status:<12} {repo}")


@app.command(
    name="attach",
)
def attach(slot: Annotated[str, tyro.conf.Positional]) -> None:
    """Attach to a detached agent's tmux session."""
    name = docker.container_name(slot)
    subprocess.run(["tmux", "attach", "-t", name])


@app.command(name="rm")
def remove(slot: Annotated[str, tyro.conf.Positional]) -> None:
    """Remove a slot (warns if unpushed work)."""
    dirty, unpushed = docker.git_status(slot)
    if dirty or unpushed:
        parts = []
        if dirty:
            parts.append(f"{dirty} uncommitted changes")
        if unpushed:
            parts.append(f"{unpushed} unpushed commits")
        warn = " + ".join(parts)
        ans = input(f"WARNING: {slot} has {warn}. Remove anyway? [y/N] ")
        if not ans.lower().startswith("y"):
            print("aborted")
            return

    name = docker.container_name(slot)
    subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    repo = paths.repos_dir() / slot
    run = paths.run_dir() / slot
    if repo.exists():
        shutil.rmtree(repo)
    if run.exists():
        shutil.rmtree(run)
    print(f"removed {slot}")


@app.command(name="clean")
def clean() -> None:
    """Remove all stopped slots (skips slots with unpushed work)."""
    run = paths.run_dir()
    if not run.exists():
        print("no slots")
        return
    print("removing all stopped slots...")
    for slot_dir in sorted(run.iterdir()):
        if not slot_dir.is_dir():
            continue
        slot = slot_dir.name
        if docker.is_running(slot):
            print(f"  skipped {slot} (running)")
            continue
        dirty, unpushed = docker.git_status(slot)
        if dirty or unpushed:
            parts = []
            if dirty:
                parts.append(f"{dirty} uncommitted")
            if unpushed:
                parts.append(f"{unpushed} unpushed")
            print(f"  skipped {slot} ({' + '.join(parts)})")
            continue
        repo = paths.repos_dir() / slot
        if repo.exists():
            shutil.rmtree(repo)
        shutil.rmtree(slot_dir)
        print(f"  removed {slot}")


@app.command(name="logs")
def logs(slot: Annotated[str, tyro.conf.Positional]) -> None:
    """Show container logs."""
    subprocess.run(["docker", "logs", docker.container_name(slot)])


@app.command(name="setup-repo")
def setup_repo(repo: Annotated[str, tyro.conf.Positional]) -> None:
    """Add bot as collaborator + apply branch protection ruleset."""
    cfg = config.load()
    if not cfg.clanker_user:
        print("Run 'clankr init' first — need clanker_user configured.")
        sys.exit(1)

    print(f"Adding {cfg.clanker_user} as collaborator to {repo}...")
    subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "PUT",
            f"repos/{repo}/collaborators/{cfg.clanker_user}",
            "-f",
            "permission=push",
        ]
    )

    ruleset = Path(__file__).parent / "ruleset.json"
    if ruleset.exists():
        import json

        ruleset_data = json.loads(ruleset.read_text())

        # Look up github_user's ID and add as bypass actor
        if cfg.github_user:
            r = subprocess.run(
                ["gh", "api", f"users/{cfg.github_user}", "--jq", ".id"],
                capture_output=True,
                text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                ruleset_data["bypass_actors"] = [
                    {
                        "actor_id": int(r.stdout.strip()),
                        "actor_type": "User",
                        "bypass_mode": "exempt",
                    }
                ]
            else:
                print(f"  warning: could not look up GitHub user ID for {cfg.github_user}")

        print(f"Applying branch protection ruleset to {repo}...")
        subprocess.run(
            ["gh", "api", "-X", "POST", f"repos/{repo}/rulesets", "--input", "-"],
            input=json.dumps(ruleset_data),
            text=True,
        )

    print()
    print("Done.")
    print(f"  Accept invitation: log in as {cfg.clanker_user} → https://github.com/notifications")


@dataclass
class ProfilesLs:
    pass


@app.command(name="profiles")
def profiles_ls(args: ProfilesLs) -> None:
    """List available profiles."""
    pdir = paths.profiles_dir()
    if not pdir.exists():
        print("no profiles — run 'clankr init'")
        return
    for p in sorted(pdir.iterdir()):
        if p.is_dir():
            has_setup = (p / "setup").exists()
            has_claude = (p / "CLAUDE.md").exists()
            extras = []
            if has_setup:
                extras.append("setup")
            if has_claude:
                extras.append("CLAUDE.md")
            print(f"  {p.name:<16} {', '.join(extras)}")


@app.command(name="init")
def init() -> None:
    """First-time setup: config + default profiles."""
    cfg = config.load()

    if not cfg.github_user:
        cfg.github_user = input("GitHub username (repo owner): ").strip()
    if not cfg.clanker_user:
        cfg.clanker_user = input("Bot GitHub username: ").strip()
    if not cfg.pat_file:
        pat = input(f"GitHub PAT for {cfg.clanker_user or 'bot account'} (classic, repo scope): ").strip()
        pat_path = paths.config_dir() / "pat"
        pat_path.parent.mkdir(parents=True, exist_ok=True)
        pat_path.write_text(pat + "\n")
        pat_path.chmod(0o600)
        cfg.pat_file = str(pat_path)
        print(f"  saved to {pat_path}")

    config.save(cfg)
    print(f"Config saved to {paths.config_file()}")

    # Copy default profiles
    bundled = Path(__file__).parent / "profiles"
    target = paths.profiles_dir()
    target.mkdir(parents=True, exist_ok=True)
    if bundled.exists():
        for profile in bundled.iterdir():
            if profile.is_dir():
                dest = target / profile.name
                if not dest.exists():
                    shutil.copytree(profile, dest)
                    print(f"  installed profile: {profile.name}")
                else:
                    print(f"  profile exists: {profile.name}")

    # Ensure data dirs
    paths.repos_dir().mkdir(parents=True, exist_ok=True)
    paths.run_dir().mkdir(parents=True, exist_ok=True)

    print("\nReady. Run: clankr launch user/project")


def main() -> None:
    app.cli(description=__doc__, config=(tyro.conf.OmitArgPrefixes,))
