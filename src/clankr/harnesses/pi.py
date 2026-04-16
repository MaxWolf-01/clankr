"""Pi coding agent harness (badlogic/pi-mono)."""

import shutil
from pathlib import Path

from clankr import paths
from clankr.harnesses import common_env_args, register


class PiHarness:
    name = "pi"

    def dockerfile_path(self) -> Path:
        user = paths.config_dir() / "Dockerfile.pi"
        if user.exists():
            return user
        return Path(__file__).parent.parent / "Dockerfile.pi"

    def image_name(self) -> str:
        return "clankr-pi"

    def setup_config_dir(self, config_dir: Path, profile_dir: Path) -> None:
        agent_dir = config_dir / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Copy auth from host
        host_auth = Path.home() / ".pi" / "agent" / "auth.json"
        if host_auth.exists():
            shutil.copy2(host_auth, agent_dir / "auth.json")

        # Context file: prefer AGENTS.md, fall back to CLAUDE.md
        for src_name, dest_name in [("AGENTS.md", "AGENTS.md"), ("CLAUDE.md", "AGENTS.md")]:
            src = profile_dir / src_name
            if src.exists():
                shutil.copy2(src, agent_dir / dest_name)
                break

        # Settings
        src = profile_dir / "settings.json"
        if src.exists():
            shutil.copy2(src, agent_dir / "settings.json")

        # System prompt override. Pi's default prompt triggers Anthropic's
        # server-side third-party detection (exact-string match). Profiles
        # should ship a pi.SYSTEM.md to neutralize this.
        src = profile_dir / "pi.SYSTEM.md"
        if src.exists():
            shutil.copy2(src, agent_dir / "SYSTEM.md")

        # Init script
        src = profile_dir / "init"
        if src.exists():
            dest = config_dir / "init"
            shutil.copy2(src, dest)
            dest.chmod(0o755)

        # Append mounts info to context file
        mounts_file = profile_dir / "mounts"
        if mounts_file.exists():
            agents_md = agent_dir / "AGENTS.md"
            with open(agents_md, "a") as f:
                f.write("\n\n## Host mounts\n\n" + mounts_file.read_text())

    def refresh_credentials(self, config_dir: Path) -> None:
        agent_dir = config_dir / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        host_auth = Path.home() / ".pi" / "agent" / "auth.json"
        if host_auth.exists():
            shutil.copy2(host_auth, agent_dir / "auth.json")

    def config_mount_args(self, config_dir: Path) -> list[str]:
        # Mount the config dir as ~/.pi inside the container (rw for token refresh)
        return ["-v", f"{config_dir}:/home/agent/.pi"]

    def session_sync_mount_args(self, host_repo_path: str, slot_run_dir: Path) -> list[str]:
        host_dir = self.host_sessions_dir(host_repo_path)
        host_dir.mkdir(parents=True, exist_ok=True)
        # Pi sessions for /work go to ~/.pi/agent/sessions/--work--/
        container_sessions = "/home/agent/.pi/agent/sessions/--work--"
        # Pre-create mount target
        (slot_run_dir / "config" / "agent" / "sessions" / "--work--").mkdir(parents=True, exist_ok=True)
        return ["-v", f"{host_dir}:{container_sessions}"]

    def env_args(self) -> list[str]:
        return common_env_args()

    def container_cmd(self, extra_args: list[str]) -> list[str]:
        return extra_args

    def encode_host_path(self, path: str) -> str:
        """Encode a host path the way pi does: /path/to/repo -> --path-to-repo--."""
        safe = path.replace("/", "-").replace("\\", "-").replace(":", "-")
        if not safe.startswith("-"):
            safe = "-" + safe
        return f"-{safe}--"

    def context_file_name(self) -> str:
        return "AGENTS.md"

    def fallback_context_file_name(self) -> str:
        return "CLAUDE.md"

    def sessions_subdir(self, slot_run_dir: Path) -> Path:
        return slot_run_dir / "config" / "agent" / "sessions" / "--work--"

    def host_sessions_dir(self, host_repo_path: str) -> Path:
        encoded = self.encode_host_path(host_repo_path)
        return Path.home() / ".pi" / "agent" / "sessions" / encoded


_instance = PiHarness()
register(_instance)
