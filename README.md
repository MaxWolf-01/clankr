# clankr

Run Claude Code in isolated Docker containers. `--dangerously-skip-permissions` without the danger.

## install

```bash
uv tool install clankr
```

## setup

```bash
clankr init
# prompts for: github username, bot username, PAT
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

## usage

```bash
clankr launch user/project                        # interactive, bare profile
clankr launch -p gsd user/project                 # GSD workflow
clankr launch -d -p gsd user/project              # detached (tmux)
clankr launch -d -p gsd -s auth-fix user/project  # named slot
clankr launch /path/to/local/repo                 # local repo

clankr run user/project -- -p "prompt"                # non-interactive, stdout capture
clankr run /path/to/repo -p ./profile -- -p "prompt"  # local repo, custom profile path

clankr attach project-1                           # reattach to detached agent
clankr save project-1 /path/to/host/repo          # export sessions to host ~/.claude/
clankr ls                                         # list slots
clankr rm project-1                               # remove (warns if unpushed)
clankr clean                                      # remove all stopped clean slots
```

```
$ clankr ls
SLOT                 PROFILE  STATUS       REPO
hello-world-1        gsd      detached     /home/max/.local/share/clankr/repos/hello-world-1
project-2            gsd      running      /home/max/.local/share/clankr/repos/project-2
project-1            bare     stopped      /home/max/.local/share/clankr/repos/project-1
```

## profiles

Each profile is an isolated claude code config — system prompt, settings, hooks, extensions.

- `bare` — claude code, skip permissions, no extras
- `gsd` — [get shit done](https://github.com/gsd-build/get-shit-done) workflow framework

`-p` takes a profile name (looked up in `~/.config/clankr/profiles/`) or a path to a profile directory. Each profile is a directory with any of:

- `CLAUDE.md` — system prompt
- `settings.json` — claude code settings
- `init` — executable script that runs **inside the container** before claude starts (install plugins, extensions, etc.)

```bash
clankr profiles                                   # list available profiles
cp -r ~/.config/clankr/profiles/gsd ~/.config/clankr/profiles/my-custom
vim ~/.config/clankr/profiles/my-custom/CLAUDE.md
```

## how it works

- each slot gets its own repo clone and claude config
- credentials copied fresh from host `~/.claude/.credentials.json` on each launch (tokens expire ~8h)
- `--dangerously-skip-permissions` baked into the container
- `-d` wraps the container in a tmux session — survives SSH disconnects
- git identity: configurable bot account with scoped PAT
- branch protection via `setup-repo`: require PR + approval for main, owner bypasses, squash-only merges

## commands

| Command | Description |
|---|---|
| `clankr init` | First-time setup: config + default profiles |
| `clankr launch` | Launch an agent (`-p` profile, `-s` slot, `-d` detach) |
| `clankr run` | Run claude non-interactively (`-p` profile, `-s` slot, `--` claude args) |
| `clankr ls` | List all slots |
| `clankr attach <slot>` | Attach to detached agent's tmux session |
| `clankr save <slot> <path>` | Export sessions to host `~/.claude/` for `claude --resume` |
| `clankr rm <slot>` | Remove slot (warns if unpushed work) |
| `clankr clean` | Remove all stopped clean slots |
| `clankr logs <slot>` | Show container logs |
| `clankr setup-repo <repo>` | Add bot collaborator + branch protection + squash merge |
| `clankr profiles` | List available profiles |
| `clankr version` | Print clankr version |

## paths

| What | Where |
|---|---|
| Config | `~/.config/clankr/config.toml` |
| Profiles | `~/.config/clankr/profiles/` |
| Dockerfile override | `~/.config/clankr/Dockerfile` |
| Repo clones | `~/.local/share/clankr/repos/` |
| Slot state | `~/.local/share/clankr/run/` |
