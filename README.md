# clankr

Run coding agents in isolated Docker containers.

Supports multiple agent harnesses:
- **claude** — [Claude Code](https://github.com/anthropics/claude-code) (`--dangerously-skip-permissions` without the danger)
- **pi** — [pi coding agent](https://github.com/badlogic/pi-mono) (badlogic/pi-mono)

## install

```bash
uv tool install clankr
```

## setup

```bash
clankr init
# prompts for: github username, bot username, PAT, default harness
```

Create a [classic PAT](https://github.com/settings/tokens/new) on the bot account with `repo` scope.

### per-repo setup (recommended)

```bash
clankr setup-repo user/project
# then accept the invitation (log in as bot → github.com/notifications)
```

This adds the bot as a collaborator and configures the repo with:
- Branch protection: PRs required for main, owner bypasses
- Squash merge only, auto-delete branch on merge

This step is optional — agents work without it, but branch protection prevents them from pushing directly to main.

### pi auth

Pi authenticates via `~/.pi/agent/auth.json` (OAuth or API key). Options:

- **API key**: set `ANTHROPIC_API_KEY` in your environment — pi reads it directly
- **pi OAuth**: run `pi` → `/login` to authenticate with a provider
- **`clankr auth`**: convert Claude CLI OAuth tokens to pi format (use at your own risk)

## usage

```bash
clankr launch user/project                        # interactive, bare profile, default harness
clankr launch -H pi user/project                  # use pi harness
clankr launch -p gsd user/project                 # GSD workflow
clankr launch -d -p gsd user/project              # detached (tmux)
clankr launch -d -p gsd -s auth-fix user/project  # named slot
clankr launch /path/to/local/repo                 # local repo

clankr run user/project -- -p "prompt"                # non-interactive, stdout capture
clankr run /path/to/repo -p ./profile -- -p "prompt"  # local repo, custom profile path

clankr sync user/project /path/to/host/repo       # register session sync mapping
clankr sync                                       # list sync mappings

clankr resume project-1                           # relaunch a stopped slot
clankr attach project-1                           # reattach to detached agent
clankr save project-1 /path/to/host/repo          # export sessions to host
clankr ls                                         # list slots
clankr rm project-1                               # remove (warns if unpushed)
clankr clean                                      # remove all stopped clean slots
```

```
$ clankr ls
SLOT                 HARNESS  PROFILE  STATUS       SYNC   REPO
hello-world-1        claude   gsd      detached     yes    /home/max/.local/share/clankr/repos/hello-world-1
project-2            pi       bare     running      -      /home/max/.local/share/clankr/repos/project-2
project-1            claude   bare     stopped      -      /home/max/.local/share/clankr/repos/project-1
```

## profiles

Each profile is an agent config — context files, settings, init scripts, host mounts.

- `bare` — minimal, skip permissions (claude) / defaults (pi)
- `gsd` — [get shit done](https://github.com/gsd-build/get-shit-done) workflow framework

`-p` takes a profile name (looked up in `~/.config/clankr/profiles/`) or a path to a profile directory. Each profile is a directory with any of:

- `CLAUDE.md` — context file for Claude Code harness
- `AGENTS.md` — context file for pi (and other) harnesses. If only one exists, it's used for both.
- `settings.json` — agent settings (format depends on target harness)
- `init` — executable script that runs **inside the container** before the agent starts (install plugins, extensions, etc.)
- `mounts` — bind-mount host paths into the container (one per line: `source:destination[:ro|rw]`, default rw, `~` expanded, `./` relative to profile dir)

```bash
clankr profiles                                   # list available profiles
cp -r ~/.config/clankr/profiles/gsd ~/.config/clankr/profiles/my-custom
vim ~/.config/clankr/profiles/my-custom/CLAUDE.md
```

## how it works

- each slot gets its own repo clone and agent config
- **harness**: `-H` selects the agent runtime (claude, pi). Default configurable via `clankr init`
- **session sync**: sessions bind-mounted to the host for the active harness's session layout
- **session preservation**: `rm`/`clean` auto-archive sessions before deleting (`--purge` to skip)
- credentials copied fresh from host on each launch (Claude: `~/.claude/.credentials.json`, pi: `~/.pi/agent/auth.json`)
- `-d` wraps the container in a tmux session — survives SSH disconnects
- git identity: configurable bot account with scoped PAT
- branch protection via `setup-repo`: require PR + approval for main, owner bypasses, squash-only merges

## commands

| Command | Description |
|---|---|
| `clankr init` | First-time setup: config + default profiles |
| `clankr launch` | Launch an agent (`-H` harness, `-p` profile, `-s` slot, `-d` detach) |
| `clankr run` | Run agent non-interactively (`-H` harness, `-p` profile, `-s` slot, `--` args) |
| `clankr ls` | List all slots |
| `clankr resume <slot>` | Relaunch a stopped slot (keeps repo, profile, sync) |
| `clankr attach <slot>` | Attach to detached agent's tmux session |
| `clankr auth` | Convert Claude CLI OAuth tokens to pi auth format |
| `clankr sync [repo] [path]` | Manage session sync mappings (list / add / `--remove`) |
| `clankr save <slot> <path>` | Export sessions to host for backup/resume |
| `clankr rm <slot>` | Remove slot, auto-archives sessions (`--purge` to skip) |
| `clankr clean` | Remove all stopped clean slots, auto-archives (`--purge` to skip) |
| `clankr logs <slot>` | Show container logs |
| `clankr setup-repo <repo>` | Add bot collaborator + branch protection + squash merge |
| `clankr profiles` | List available profiles |
| `clankr version` | Print clankr version |

## paths

| What | Where |
|---|---|
| Config | `~/.config/clankr/config.toml` |
| Sync mappings | `~/.config/clankr/sync_map.json` |
| Profiles | `~/.config/clankr/profiles/` |
| Dockerfile override | `~/.config/clankr/Dockerfile.{claude,pi}` |
| Repo clones | `~/.local/share/clankr/repos/` |
| Slot state | `~/.local/share/clankr/run/` |
| Archived sessions | `~/.local/share/clankr/sessions/` |
