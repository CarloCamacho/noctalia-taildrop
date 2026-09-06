# noctalia-taildrop

**Send a file to any machine on your tailnet straight from HyprFM's right-click menu**

`noctalia-taildrop` adds a **"Send via Taildrop…"** action to HyprFM. Right-click a
file, pick a device, confirm, and Tailscale copies it across. It reuses the Tailscale
plugin's own panel as a device picker, so you get an honest destination list and a
confirmation step before anything leaves your machine.

> Files only, by design — `tailscale file cp` does not support directories (see
> [Limitations](#limitations)).

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
  - [1. Install the Tailscale plugin (override)](#1-install-the-tailscale-plugin-override)
  - [2. Install the bridge helper](#2-install-the-bridge-helper)
  - [3. Wire up the HyprFM context menu](#3-wire-up-the-hyprfm-context-menu)
  - [4. Grant the Tailscale daemon operator (one-time)](#4-grant-the-tailscale-daemon-operator-one-time)
- [Usage](#usage)
- [IPC contract](#ipc-contract)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Development](#development)
- [License](#license)

---

## What it does

| From | Outcome |
| --- | --- |
| HyprFM right-click → **Send via Taildrop…** | Opens the Tailscale panel with the file pre-loaded |
| In the panel | Choose an eligible device, review file + destination, confirm |
| After confirm | Runs `tailscale file cp <file> <device>:` and shows the result |
| Folders | Not supported — you get a clear notification instead of a silent no-op |

## How it works

```text
HyprFM right-click
  └─ runs noctalia-taildrop %f            (one helper per selected file)
       └─ validates the path, builds a structured request
            └─ `noctalia msg plugin davemhammer/tailscale:service all taildrop_send '<json>'`
                 └─ Tailscale service validates + records a `ts_transfer` job
                      └─ opens the Tailscale panel (Send tab)
                           └─ you pick a device and confirm
                                └─ service runs `tailscale file cp <file> <device>:`
```

- The helper never shells out — the path crosses the boundary as a discrete argv
  element and a JSON payload, so filenames with spaces / quotes / newlines survive.
- The picker lists only **eligible** Taildrop destinations (from `tailscale file cp --targets`),
  not every peer on the tailnet.

## Requirements

- [Tailscale](https://tailscale.com/download) CLI (`tailscale` on `PATH`, daemon running)
- [Noctalia](https://noctalia.dev) with the `davemhammer/tailscale` plugin
- Optional but the whole point: **HyprFM** (or any file manager that passes a path like `%f`)
- `python3` for the bridge helper
- The local user must be a **Tailscale daemon operator** (see step 4)

## Installation

> The bundled Tailscale plugin keeps its original id `davemhammer/tailscale`, so it
> is a **drop-in override** of the community version. It deliberately replaces the
> plugin so the Send tab appears inside the panel you already use.

### 1. Install the Tailscale plugin (override)

The modified plugin lives at [`plugin/tailscale/`](plugin/tailscale). Copy it into a
Noctalia **path source** directory — the folder name must match the plugin's id suffix:

```sh
# Example: reuse the `carlo-local` path source already used for other plugins
mkdir -p ~/noctalia-sources/tailscale
cp -a plugin/tailscale/. ~/noctalia-sources/tailscale/
```

If you don't have a path source yet, register one (or edit `~/.config/noctalia/settings.toml`):

```toml
[[plugins.source]]
kind = "path"
location = "/home/you/noctalia-sources"
name = "local"
```

Then enable the plugin and confirm it loads from your path source:

```sh
noctalia msg plugins disable davemhammer/tailscale
noctalia msg plugins enable davemhammer/tailscale
noctalia msg plugins list | grep tailscale
# expect: davemhammer/tailscale [local] 1.0.6 enabled ...
```

> Editing `panel.luau` / `service.luau` in the path-source folder hot-reloads those
> entries, so you can iterate without re-enabling.

### 2. Install the bridge helper

```sh
install -m 755 bin/noctalia-taildrop ~/.local/bin/noctalia-taildrop
```

Confirm it works and the path is on `PATH` for HyprFM (use the absolute path in step 3
if `~/.local/bin` isn't on HyprFM's `PATH`).

### 3. Wire up the HyprFM context menu

Append the block from [`hyprfm/context-menu.toml`](hyprfm/context-menu.toml) to `~/.config/hyprfm/config.toml`:

```toml
[context_menu]

[[context_menu.actions]]
name = "Send via Taildrop…"
command = "/home/you/.local/bin/noctalia-taildrop %f"
types = ["*"]
```

Restart HyprFM. Back up your config first:

```sh
cp ~/.config/hyprfm/config.toml ~/.config/hyprfm/config.toml.bak
```

> HyprFM runs the action **once per selected file** and passes the path via `%f` as a
> discrete argv element (no shell). Multi-selecting therefore opens one picker per file.

### 4. Grant the Tailscale daemon operator (one-time)

`tailscale file cp`, `tailscale set`, etc. require the local user to be the daemon
**operator**. If you ever see `Access denied: file access denied`, run once:

```sh
sudo tailscale set --operator=$USER
```

This is a local daemon setting; it does **not** change tailnet policy or who may
receive files.

## Usage

1. Right-click a file in HyprFM → **Send via Taildrop…**
2. The Tailscale panel opens on the **Send to device** tab with your file listed.
3. Pick a destination (online devices first; offline ones are shown but may fail).
4. Confirm — the destination + filename are visible before you send.
5. A notification reports success or a real CLI error.

## IPC contract

The bridge talks to the Tailscale service over Noctalia's `msg plugin` channel.
See [docs/ipc-contract.md](docs/ipc-contract.md) for the full spec.

**Request** (helper → service):

```
noctalia msg plugin davemhammer/tailscale:service all taildrop_send '<json>'
```

```json
{ "v": 1, "requestId": "<uuid>", "paths": ["/abs/path"], "origin": "hyprfm" }
```

**Shared job** (state key `ts_transfer`): `requestId`, `paths`, `target`, `phase`
(`choosing|confirming|sending|succeeded|failed|cancelled`), `status`, `error`,
`eligible`, timestamps, `revision`.

The service rejects requests that are malformed, non-absolute, or point at a
directory — bounds are enforced (≤ 32 paths, ≤ 8 KiB, ≤ 4096 bytes/path).

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `Access denied: file access denied` when sending | Run `sudo tailscale set --operator=$USER` once |
| Folder right-click does nothing / shows a notice | Folders aren't supported by `tailscale file cp`; archive it first |
| Panel opens but no devices listed | `tailscale file cp --targets` returned nothing (no eligible devices, or daemon down) |
| "Send via Taildrop…" not in the HyprFM menu | Restart HyprFM; confirm the config block and helper path |
| Plugin not loaded from your copy | Check `noctalia msg plugins list` shows your path source, not `community` |
| Helper exits 1 with a message on stderr | Look at the message (missing/relative/unreadable path) |

## Limitations

- **Files only.** `tailscale file cp` rejects directories. A future v2 could
  archive-on-send (send `folder.tar.gz`) or delegate to `tailscale file cp` with a
  pre-archived path.
- **One file per invocation.** HyprFM runs the action once per selected item, so
  multi-select spawns a picker per file (documented, not batched).
- **No receive flow.** Receiving (`tailscale file get`) is out of scope for this repo.
- Offline/`offline, last seen …` peers are listed but a send may fail; eligibility is
  the CLI's call, not the plugin's.

## Development

```sh
# Run the bridge unit tests (no live Noctalia needed)
python3 -m unittest -v tests.test_bridge
```

Layout:

```text
plugin/tailscale/   modified davemhammer/tailscale plugin (service, panel, translations)
bin/                the noctalia-taildrop bridge helper
hyprfm/             sample context-menu config block
docs/               the IPC contract
tests/              bridge tests
```

Upstream contribution: the plugin-side changes are intended for
[`noctalia-dev/community-plugins`](https://github.com/noctalia-dev/community-plugins)
under `tailscale/`. This repo bundles them as a self-contained override and adds the
HyprFM bridge + docs; the plan is to contribute the service/panel/translation changes
upstream and keep this repo as the integration/distribution point.

## License

MIT — see [LICENSE](LICENSE). The bundled Tailscale plugin is a modified copy of
`davemhammer/tailscale` (MIT, © its authors). Not affiliated with Noctalia or Tailscale.
