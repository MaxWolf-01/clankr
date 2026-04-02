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
from importlib.metadata import version as pkg_version
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
            docker.refresh_credentials(slot)
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

    # Resolve sync target
    sync_target = ""
    if Path(repo_url).is_dir():
        sync_target = repo_url
    else:
        key = config.normalize_repo(args.repo)
        if key:
            sync_target = config.load_sync_map().get(key, "")

    sync_args: list[str] = []
    if sync_target:
        migrated = docker.migrate_sessions_to_sync(slot, sync_target)
        if migrated:
            print(f"Migrated {migrated} existing session(s) → {sync_target}")
        sync_args = docker.sync_mount_args(sync_target, slot)
        docker.save_sync_target(slot, sync_target)
    else:
        docker.clear_sync_target(slot)

    docker.build_image()
    docker.refresh_credentials(slot)

    name = docker.container_name(slot)

    common = [
        "-v",
        f"{repo_dir}:/work",
        "-v",
        f"{claude_dir}:/home/agent/.claude",
        *sync_args,
        *docker.env_args(),
    ]

    sync_msg = f", sync: {sync_target}" if sync_target else ""
    print(f"Launching {name} (profile: {args.profile}{sync_msg})")

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


@dataclass
class Run:
    repo: Annotated[str, tyro.conf.Positional]
    """Repository: user/project, https://github.com/user/project, or /local/path."""
    profile: Annotated[str, tyro.conf.arg(aliases=["-p"])] = "bare"
    """Profile to use. See 'clankr profiles ls'."""
    slot: Annotated[str, tyro.conf.arg(aliases=["-s"])] = ""
    """Slot name. Defaults to repo name."""
    claude_args: Annotated[list[str], tyro.conf.Positional, tyro.conf.UseAppendAction] = field(default_factory=list)
    """Arguments passed to claude (after --)."""


@app.command(name="run")
def run_cmd(args: Run) -> None:
    """Run claude non-interactively in a container. Stdout is clean for capture."""
    repo_url = docker.expand_repo_url(args.repo)
    base = args.slot or Path(repo_url.rstrip("/")).stem.removesuffix(".git")

    if args.slot:
        slot = args.slot
        state = docker.container_state(slot)
        if state == "running":
            print(f"Slot {slot} is already running.", file=sys.stderr)
            sys.exit(1)
        elif state is not None:
            docker.remove_container(slot)
    else:
        slot = docker.next_slot(base)

    # Local paths: mount directly. URLs: clone.
    local_path = Path(repo_url)
    if local_path.is_dir():
        repo_dir = local_path
    else:
        repo_dir = docker.clone_repo(repo_url, slot)

    claude_dir = docker.setup_slot(slot, args.profile)

    # Resolve sync target
    sync_target = ""
    if Path(repo_url).is_dir():
        sync_target = repo_url
    else:
        key = config.normalize_repo(args.repo)
        if key:
            sync_target = config.load_sync_map().get(key, "")

    sync_args: list[str] = []
    if sync_target:
        migrated = docker.migrate_sessions_to_sync(slot, sync_target)
        if migrated:
            print(f"Migrated {migrated} existing session(s) → {sync_target}", file=sys.stderr)
        sync_args = docker.sync_mount_args(sync_target, slot)
        docker.save_sync_target(slot, sync_target)
        print(f"Session sync → {sync_target}", file=sys.stderr)
    else:
        docker.clear_sync_target(slot)

    docker.build_image()
    docker.refresh_credentials(slot)

    name = docker.container_name(slot)

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "-v",
            f"{repo_dir}:/work",
            "-v",
            f"{claude_dir}:/home/agent/.claude",
            *sync_args,
            docker.IMAGE_NAME,
            *args.claude_args,
        ],
    )
    sys.exit(result.returncode)


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
    print(f"{'SLOT':<20} {'PROFILE':<8} {'STATUS':<12} {'SYNC':<6} REPO")
    for s in slots:
        profile = docker.slot_profile(s)
        status = docker.slot_status(s)
        sync = "yes" if docker.get_sync_target(s) else "-"
        repo = paths.repos_dir() / s
        print(f"{s:<20} {profile:<8} {status:<12} {sync:<6} {repo}")


@dataclass
class Resume:
    slot: Annotated[str, tyro.conf.Positional]
    """Slot name to resume."""
    detach: Annotated[bool, tyro.conf.arg(aliases=["-d"])] = False
    """Run in a tmux session (detached)."""
    claude_args: Annotated[list[str], tyro.conf.Positional, tyro.conf.UseAppendAction] = field(default_factory=list)
    """Extra arguments passed to claude (after --)."""


@app.command(name="resume")
def resume(args: Resume) -> None:
    """Resume a stopped slot with its original repo, profile, and sync config."""
    slot = args.slot
    repo_dir = paths.repos_dir() / slot
    run = paths.run_dir() / slot

    if not run.exists():
        print(f"Slot not found: {slot}", file=sys.stderr)
        sys.exit(1)

    state = docker.container_state(slot)
    if state == "running":
        print(f"Slot {slot} is already running. Attaching...")
        docker.refresh_credentials(slot)
        name = docker.container_name(slot)
        r = subprocess.run(["tmux", "has-session", "-t", name], capture_output=True)
        if r.returncode == 0:
            subprocess.run(["tmux", "attach", "-t", name])
        else:
            subprocess.run(["docker", "attach", name])
        return
    elif state is not None:
        docker.remove_container(slot)

    if not repo_dir.exists():
        print(f"Repo clone not found for slot: {slot}", file=sys.stderr)
        sys.exit(1)

    claude_dir = run / ".claude"
    profile = docker.slot_profile(slot)
    sync_target = docker.get_sync_target(slot) or ""

    sync_args: list[str] = []
    if sync_target:
        sync_args = docker.sync_mount_args(sync_target, slot)

    docker.build_image()
    docker.refresh_credentials(slot)

    name = docker.container_name(slot)

    common = [
        "-v",
        f"{repo_dir}:/work",
        "-v",
        f"{claude_dir}:/home/agent/.claude",
        *sync_args,
        *docker.env_args(),
    ]

    sync_msg = f", sync: {sync_target}" if sync_target else ""
    print(f"Resuming {name} (profile: {profile}{sync_msg})")

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


@app.command(
    name="attach",
)
def attach(slot: Annotated[str, tyro.conf.Positional]) -> None:
    """Attach to a detached agent's tmux session."""
    docker.refresh_credentials(slot)
    name = docker.container_name(slot)
    subprocess.run(["tmux", "attach", "-t", name])


@app.command(name="rm")
def remove(
    slot: Annotated[str, tyro.conf.Positional],
    purge: bool = False,
) -> None:
    """Remove a slot (warns if unpushed work). Sessions are archived unless --purge."""
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

    if not purge and config.load().save_sessions != "false":
        sync_target = docker.get_sync_target(slot)
        if sync_target:
            print(f"  sessions synced to {sync_target}")
        else:
            saved = docker.archive_sessions(slot)
            if saved:
                print(f"  archived {saved} session(s) → {paths.sessions_dir() / slot}")

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


@app.command(name="save")
def save(
    slot: Annotated[str, tyro.conf.Positional],
    host_path: Annotated[str, tyro.conf.Positional],
) -> None:
    """Save session files from a slot to the host's ~/.claude/ for backup/resume."""
    slot_projects = paths.run_dir() / slot / ".claude" / "projects" / "-work"
    if not slot_projects.exists():
        print(f"No sessions found in slot {slot}")
        sys.exit(1)

    encoded = docker.encode_host_path(host_path)
    host_projects = Path.home() / ".claude" / "projects" / encoded
    host_projects.mkdir(parents=True, exist_ok=True)

    copied = 0
    for item in slot_projects.iterdir():
        if item.name == "memory":
            continue
        dest = host_projects / item.name
        if item.is_file() and item.suffix == ".jsonl":
            shutil.copy2(item, dest)
            copied += 1
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)

    print(f"Saved {copied} session(s) from {slot} → {host_projects}")


@app.command(name="sync")
def sync_cmd(
    repo: Annotated[str, tyro.conf.Positional] = "",
    host_path: Annotated[str, tyro.conf.Positional] = "",
    remove: bool = False,
) -> None:
    """Manage session sync mappings (repo → host path)."""
    if not repo:
        mapping = config.load_sync_map()
        if not mapping:
            print("no sync mappings")
            return
        for r, p in sorted(mapping.items()):
            print(f"  {r:<30} → {p}")
        return

    key = config.normalize_repo(repo)
    if not key:
        print(f"Cannot normalize repo: {repo!r}", file=sys.stderr)
        print("  Expected: user/project or a GitHub URL", file=sys.stderr)
        sys.exit(1)

    mapping = config.load_sync_map()

    if remove:
        if key in mapping:
            del mapping[key]
            config.save_sync_map(mapping)
            print(f"removed sync mapping for {key}")
        else:
            print(f"no sync mapping for {key}")
        return

    if not host_path:
        if key in mapping:
            print(f"{key} → {mapping[key]}")
        else:
            print(f"no sync mapping for {key}")
        return

    resolved = str(Path(host_path).expanduser().resolve())
    mapping[key] = resolved
    config.save_sync_map(mapping)
    print(f"sync: {key} → {resolved}")


@app.command(name="clean")
def clean(purge: bool = False) -> None:
    """Remove all stopped slots (skips slots with unpushed work). Sessions are archived unless --purge."""
    run = paths.run_dir()
    if not run.exists():
        print("no slots")
        return

    cfg = config.load()
    should_save = not purge and cfg.save_sessions != "false"

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

        if should_save and not docker.get_sync_target(slot):
            saved = docker.archive_sessions(slot)
            if saved:
                print(f"  archived {saved} session(s) from {slot}")

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

        print(f"Applying branch protection ruleset to {repo}...")
        subprocess.run(
            ["gh", "api", "-X", "POST", f"repos/{repo}/rulesets", "--input", "-"],
            input=json.dumps(ruleset_data),
            text=True,
        )

    print("Configuring squash merge as default...")
    subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "PATCH",
            f"repos/{repo}",
            "-F",
            "allow_squash_merge=true",
            "-F",
            "allow_merge_commit=false",
            "-F",
            "allow_rebase_merge=false",
            "-F",
            "delete_branch_head_on_merge=true",
            "-f",
            "squash_merge_commit_title=PR_TITLE",
            "-f",
            "squash_merge_commit_message=PR_BODY",
        ]
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
            has_init = (p / "init").exists()
            has_claude = (p / "CLAUDE.md").exists()
            extras = []
            if has_init:
                extras.append("init")
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


@app.command(name="version")
def version() -> None:
    """Print the clankr version."""
    print(pkg_version("clankr"))


def main() -> None:
    app.cli(description=__doc__, config=(tyro.conf.OmitArgPrefixes,))
