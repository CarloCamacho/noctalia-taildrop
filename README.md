# noctalia-taildrop

**Send a file to any machine on your tailnet straight from a file manager's right-click menu.**

`noctalia-taildrop` is a small, standalone [Noctalia](https://noctalia.dev) plugin. Right-click a
file, pick a device, confirm, and Tailscale copies it across. It does **not** replace your
Tailscale frontend — install a Tailscale plugin separately if you want the VPN manager / peers /
exit-node UI.

It ships a purpose-built **send dialog** — a single Noctalia panel that lists eligible Taildrop
destinations and requires an explicit confirm before anything leaves your machine.

> ✅ Published on the Noctalia community plugin store as `carlocamacho/taildrop` (v1.0.0). Install it
> directly from Noctalia's community source; this repo is the upstream source of truth.

> Files are sent as-is; **folders are auto-archived to a `.tar.gz`** at send time (since
> `tailscale file cp` only accepts files). See [Limitations](#limitations).

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
  - [1. Install the plugin](#1-install-the-plugin)
  - [2. Install the bridge helper](#2-install-the-bridge-helper)
  - [3. Wire up a file manager](#3-wire-up-a-file-manager)
  - [4. Grant the Tailscale daemon operator (one-time)](#4-grant-the-tailscale-daemon-operator-one-time)
- [Usage](#usage)
- [File managers](#file-managers)
- [IPC contract](#ipc-contract)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Development](#development)
- [License](#license)

---

## What it does

| From | Outcome |
| --- | --- |
| File manager right-click → **Send via Taildrop…** | Opens the Taildrop send dialog with your file(s) pre-loaded |
| In the dialog | Choose an eligible device, review file(s) + destination, confirm |
| After confirm | Runs `tailscale file cp <file> <device>:` and shows the result |
| Folders | Archived to `<name>.tar.gz` in a private temp dir, sent, then cleaned up |
| Send fails | The dialog stays open with the error — **Retry** re-sends to the same device |

## How it works

```text
File manager right-click
  └─ runs noctalia-taildrop <file> [more files...]     (one helper per action)
       └─ validates each path (no shell), builds a structured request
            └─ `noctalia msg plugin carlocamacho/taildrop:service all taildrop_send '<json>'`
            └─ `noctalia msg panel-open carlocamacho/taildrop:send`   (always shows the dialog)
                 └─ service records a `taildrop_transfer` job
                      └─ the send dialog lists eligible destinations
                           └─ you pick a device and confirm
                                └─ service runs `tailscale file cp <file> <device>:`
                                   (directories are archived to .tar.gz first)
```

- The bridge never shells out — paths cross the boundary as discrete argv elements and a JSON
  payload, so filenames with spaces / quotes / newlines survive intact.
- The dialog lists only **eligible** Taildrop destinations (from `tailscale file cp --targets`),
  not every peer on the tailnet.
- The dialog is opened with `noctalia msg panel-open`, which is **non-toggle** — so a second
  send brings the already-open dialog forward instead of closing it.

## Requirements

- [Tailscale](https://tailscale.com/download) CLI (`tailscale` on `PATH`, daemon running)
- [Noctalia](https://noctalia.dev)
- Optional but the whole point: a file manager (HyprFM, Nautilus, Dolphin, Thunar, …)
- `python3` for the bridge helper
- `tar` and `mktemp` on `PATH` — only used when you send a folder (default on Linux/macOS)
- The local user must be a **Tailscale daemon operator** (see step 4)

## Installation

### 1. Install the plugin

Copy the plugin into a Noctalia **path source** directory. The folder name must match the
plugin's name suffix (`taildrop`):

```sh
# Example: reuse the `carlo-local` path source already used for other plugins
mkdir -p ~/noctalia-sources/taildrop
cp -a plugin/taildrop/. ~/noctalia-sources/taildrop/
```

If you don't have a path source yet, register one (or edit `~/.config/noctalia/settings.toml`):

```toml
[[plugins.source]]
kind = "path"
location = "/home/you/noctalia-sources"
name = "local"
```

Then enable the plugin and confirm it loads:

```sh
noctalia msg plugins enable carlocamacho/taildrop
noctalia msg plugins list | grep taildrop
# expect: carlocamacho/taildrop [local] 1.0.0 enabled requires tailscale
```

> Editing `panel.luau` / `service.luau` in the path-source folder hot-reloads those
> entries, so you can iterate without re-enabling.

### 2. Install the bridge helper

```sh
install -m 755 bin/noctalia-taildrop ~/.local/bin/noctalia-taildrop
```

Confirm it works and the path is on `PATH` for your file manager (use the absolute path in
step 3 if `~/.local/bin` isn't on the manager's `PATH`).

### 3. Wire up a file manager

Pick your manager below and follow its example. **HyprFM**, **Nautilus**, **Dolphin**, and
**Thunar** examples live in [`integration/`](integration/).

### 4. Grant the Tailscale daemon operator (one-time)

`tailscale file cp`, `tailscale set`, etc. require the local user to be the daemon
**operator**. If you ever see `Access denied: file access denied`, run once:

```sh
sudo tailscale set --operator=$USER
```

This is a local daemon setting; it does **not** change tailnet policy or who may receive files.

## Usage

1. Right-click a file → **Send via Taildrop…**
2. The send dialog lists the file(s) and the eligible destinations (online first).
3. Pick a destination; the destination + filename(s) are visible before you send.
4. Confirm — a notification reports success or a real CLI error.

After a **successful** send the dialog closes on its own after a couple of seconds (the
result notification is what you'll see). A **failed** send stays open with the error so you can
read it — press **Done** to dismiss.

## File managers

The bridge accepts **one or more** absolute path arguments. Pass all selected files at once
where the manager supports it, so a multi-select becomes a single dialog:

| Manager | Selected files placeholder | How it passes them |
| --- | --- | --- |
| HyprFM | `%f` | One invocation per selected item (the helper coalesces into one dialog) |
| Nautilus | `$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS` | All selected paths in one invocation |
| Dolphin | `%F` (or `%f`) | All selected files (`%F`) in one invocation |
| Thunar | `%f` | One invocation per selected item |

> If your manager passes one file per invocation, multiple selections still work — the plugin
> coalesces concurrent requests that arrive within a moment into a single dialog.

## IPC contract

The bridge talks to the service over Noctalia's `msg plugin` channel and opens the dialog with
`msg panel-open`. See [docs/ipc-contract.md](docs/ipc-contract.md) for the full spec.

**Request** (bridge → service):

```
noctalia msg plugin carlocamacho/taildrop:service all taildrop_send '<json>'
```

```json
{ "v": 1, "requestId": "<uuid>", "paths": ["/abs/path", "/abs/path2"], "origin": "file_manager" }
```

**Open the dialog** (bridge → Noctalia, non-toggle):

```
noctalia msg panel-open carlocamacho/taildrop:send
```

**Shared job** (state key `taildrop_transfer`): `requestId`, `paths`, `target`, `phase`
(`choosing|confirming|sending|succeeded|failed|cancelled`), `status`, `error`, `eligible`,
timestamps, `revision`.

The service rejects requests that are malformed, non-absolute, or over-limit — bounds
are enforced (≤ 32 paths, ≤ 8 KiB, ≤ 4096 bytes/path). Directories are allowed and archived
at send time.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `Access denied: file access denied` when sending | Run `sudo tailscale set --operator=$USER` once |
| Folder send takes a while / temp files linger | Folders are archived with `tar` (needs `tar` + `mktemp`). Temp files are removed after the send |
| Dialog opens but no devices listed | `tailscale file cp --targets` returned nothing (no eligible devices, or daemon down) |
| "Send via Taildrop…" not in the menu | Restart the file manager; confirm the config block and helper path |
| Plugin not loaded from your copy | Check `noctalia msg plugins list` shows your path source, and the folder is named `taildrop` |
| Helper exits 1 with a message on stderr | Look at the message (missing/relative/unreadable path) |
| Dialog opens from a bare `msg plugin` call but not with the helper | Only the bridge helper runs `msg panel-open`; call it directly if you invoke the plugin by hand |

## Limitations

- **Folders are archived, not sent as-is.** A directory is packed to `<name>.tar.gz` in a private
temp dir (`mktemp -d`, mode 0700), sent, then deleted. Requires `tar` and `mktemp` (present on
Linux/macOS). Very large folders take time to compress and use temporary disk space.
- **No receive flow.** Receiving (`tailscale file get`) is out of scope for this repo.
- Offline/`offline, last seen …` peers are listed but a send may fail; eligibility is the CLI's
  call, not the plugin's.

## Development

```sh
# Run the bridge unit tests (no live Noctalia needed)
python3 -m unittest -v tests.test_bridge
```

Layout:

```text
plugin/taildrop/   standalone Noctalia plugin (service, send dialog, translations)
bin/               the noctalia-taildrop bridge helper
hyprfm/            sample HyprFM context-menu config block
integration/       samples for Nautilus, Dolphin, Thunar
docs/              the IPC contract
tests/             bridge tests
```

## License

MIT — see [LICENSE](LICENSE). Noctalia and Tailscale are registered trademarks of their
respective owners; this project is not affiliated with or endorsed by either. The Tailscale mark
shown in the dialog is the [Simple Icons](https://simpleicons.org) glyph (CC0), used as an
informative brand cue, not an endorsement.
