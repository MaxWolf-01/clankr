"""Claude Code harness."""

import json
import shutil
from pathlib import Path

from clankr import paths
from clankr.harnesses import common_env_args, register


class ClaudeHarness:
    name = "claude"

    def dockerfile_path(self) -> Path:
        user = paths.config_dir() / "Dockerfile.claude"
        if user.exists():
            return user
        return Path(__file__).parent.parent / "Dockerfile.claude"

    def image_name(self) -> str:
        return "clankr-claude"

    def setup_config_dir(self, config_dir: Path, profile_dir: Path) -> None:
        config_dir.mkdir(parents=True, exist_ok=True)

        # Copy credentials from host
        host_creds = Path.home() / ".claude" / ".credentials.json"
        if host_creds.exists():
            shutil.copy2(host_creds, config_dir / ".credentials.json")

        # Seed .claude.json for TUI onboarding bypass
        (config_dir / ".claude.json").write_text(
            json.dumps({"hasCompletedOnboarding": True, "installMethod": "npm", "numStartups": 5})
        )

        # Context file: prefer CLAUDE.md, fall back to AGENTS.md
        for src_name, dest_name in [("CLAUDE.md", "CLAUDE.md"), ("AGENTS.md", "CLAUDE.md")]:
            src = profile_dir / src_name
            if src.exists():
                shutil.copy2(src, config_dir / dest_name)
                break

        src = profile_dir / "claude.settings.json"
        if src.exists():
            shutil.copy2(src, config_dir / "settings.json")

        src = profile_dir / "init"
        if src.exists():
            dest = config_dir / "init"
            shutil.copy2(src, dest)
            dest.chmod(0o755)

        mounts_file = profile_dir / "mounts"
        if mounts_file.exists():
            with open(config_dir / "CLAUDE.md", "a") as f:
                f.write("\n\n## Host mounts\n\n" + mounts_file.read_text())

    def refresh_credentials(self, config_dir: Path) -> None:
        host_creds = Path.home() / ".claude" / ".credentials.json"
        if host_creds.exists() and config_dir.exists():
            shutil.copy2(host_creds, config_dir / ".credentials.json")

    def config_mount_args(self, config_dir: Path) -> list[str]:
        return ["-v", f"{config_dir}:/home/agent/.claude"]

    def session_sync_mount_args(self, host_repo_path: str, slot_run_dir: Path) -> list[str]:
        host_dir = self.host_sessions_dir(host_repo_path)
        host_dir.mkdir(parents=True, exist_ok=True)
        return ["-v", f"{host_dir}:/home/agent/.claude/projects/-work"]

    def env_args(self, config_dir: Path) -> list[str]:
        return common_env_args()

    def container_cmd(self, extra_args: list[str]) -> list[str]:
        return extra_args

    def encode_host_path(self, path: str) -> str:
        """Encode a host path the way Claude does: /path/to/repo -> -path-to-repo."""
        encoded = path.replace("/", "-")
        if not encoded.startswith("-"):
            encoded = "-" + encoded
        return encoded

    def context_file_name(self) -> str:
        return "CLAUDE.md"

    def fallback_context_file_name(self) -> str:
        return "AGENTS.md"

    def sessions_subdir(self, slot_run_dir: Path) -> Path:
        return slot_run_dir / "config" / "projects" / "-work"

    def host_sessions_dir(self, host_repo_path: str) -> Path:
        encoded = self.encode_host_path(host_repo_path)
        return Path.home() / ".claude" / "projects" / encoded


_instance = ClaudeHarness()
register(_instance)
