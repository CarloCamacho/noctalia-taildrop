# Taildrop Send-Request IPC Contract

> Shared interface between the **Tailscale plugin** (`davemhammer/tailscale`) and
> external callers (currently HyprFM). This is a **design decision**, not an
> implementation. Nothing here is deployed or changed yet.

## Decision: use Noctalia `msg plugin` event IPC with a structured JSON payload

The primary channel for handing file paths into the plugin is **Noctalia's existing
`noctalia msg plugin` IPC**, carrying a small JSON payload on the `[payload]`
argument. A private **request file** is kept only as a documented fallback (see below),
**not** the primary mechanism.

### Why this is viable (verified against the installed setup)

- `noctalia msg plugin <id:entry> <target> <event> [payload]` dispatches to the
  plugin entry's Lua `onIpc(event, payload)`. This is the terminal point for every
  `msg plugin` call.
- The `payload` argument is delivered as either a **string** or a **decoded table**.
  First-party plugins already read object fields from it:
  - `noctalia/bitwarden` `onIpc` reads `payload.password`, `payload.id`, `payload.mode`,
    `payload.clientId` (`if type(payload) == "table" then …`).
  - `yuuto/arch-updater` `onIpc` reads `payload.pkg`, `payload.at` (`type(payload)=="table"`).
  - `davemhammer/tailscale` already does `type(payload)=="table" and payload.action`.
- A plugin **service can open its own panel** with `noctalia.togglePanel("<id>:<entry>")`
  (used by bitwarden for `open_panel`), so the helper only needs a single trigger call.

The one thing to confirm before coding is empirical: the exact decoding semantics of
the `msg` `payload` argument (does a JSON object always arrive as a table?). See
**Task 0** below.

---

## Transport

### Helper → service (one call, no shell)

```sh
noctalia msg plugin davemhammer/tailscale:service all taildrop_send '<json>'
```

The helper (Python) builds `json` with `json.dumps(...)` and passes it as a **single
argv element** via `subprocess.run([...], shell=False)`. **Never** build this string
in a shell. Noctalia decodes it into `payload`.

### Event name

`taildrop_send` — namespaced to avoid colliding with the plugin's existing
`refresh` / `up` / `down` / `toggle` events and its `payload.action` fallthrough.

---

## Request schema (client → service)

Delivered as `onIpc("taildrop_send", payload)` where `payload` is the decoded table.

| Field | Type | Rules |
| --- | --- | --- |
| `v` | int | `= 1` (contract version) |
| `requestId` | string | ASCII `[A-Za-z0-9._-]`, length 1..64, unique per request; used only for correlation |
| `paths` | string[] | 1..32 entries; each an **absolute** local path, ≤4096 bytes |
| `origin` | string (optional) | `"hyprfm"` — informational only, not trusted |

**Bounds (validate in the service):** total JSON ≤ 8 KiB; `paths` count ≤ 32.
Reject anything outside these limits without opening a panel.

---

## Transfer job (shared state, key `ts_transfer`)

The plugin writes a **shared job** that both the panel and the service read. This is
the "request ID + structured file payload + phase" state the plans require.

| Field | Type | Notes |
| --- | --- | --- |
| `requestId` | string | echo from the request |
| `paths` | string[] | validated absolute paths |
| `target` | string | `""` until the user picks; then `<hostname or ip>` |
| `phase` | enum | `choosing` \| `confirming` \| `sending` \| `succeeded` \| `failed` \| `cancelled` |
| `status` | string | human status line (never a fake percentage) |
| `error` | string | populated on `failed` |
| `eligible` | array | targets from `tailscale file cp --targets`: `{name, ip, online}` |
| `createdAt` / `updatedAt` | number | epoch seconds |
| `revision` | number | bumped on every write so the panel can detect change |

---

## Flow

1. **Helper** validates the file: absolute path, exists, is a regular file, readable.
   (Paths are never passed on a shell command line.)
2. Helper builds the request JSON and calls `noctalia msg plugin … all taildrop_send '<json>'`.
3. **Service** `onIpc("taildrop_send", payload)`:
   - Decode `payload` if it arrives as a string (`noctalia.json.decode`).
   - Validate fields and bounds; on failure, set a clear error and **do not** open a panel.
   - On success: write `ts_transfer` (phase=`choosing`, `eligible` from
     `tailscale file cp --targets`), then `noctalia.togglePanel("davemhammer/tailscale:manager")`.
4. **Panel** watches `ts_transfer`. If a job is active, render "Send N file(s) →" with
   the eligible-target list. User selects a target → `phase=confirming`, showing the
   destination and the filename(s) plus a confirm/cancel.
5. **Confirm** → panel sends `send("taildrop_confirm", { requestId, target })` (existing
   `ts_command` state watch).
6. **Service** `executeAction` for `taildrop_confirm`:
   - Re-validate that each path still exists, is a regular file, and has not changed size.
   - Run `tailscale file cp <paths…> <target>:` as an argv vector through the existing
     `runAction` / `runTs` (which shell-quotes each element; **no raw concatenation**).
   - `phase=sending` → `succeeded` / `failed`; notify the outcome; set `ts_action_result`.
7. **Cancel** → `phase=cancelled`; clear the active job.

---

## Security invariants

- **No shell** anywhere: the helper uses `subprocess` with an argv list; the service
  builds argv with its existing `shellCommand` (quotes each element) for `noctalia.runAsync`.
- Paths are **data**, never interpolated into a command string.
- Payload is bounded; non-table / over-limit / empty-path / non-absolute / non-regular-file
  requests are rejected without side effects.
- `requestId` is charset/length-validated and used only for correlation.
- Eligibility comes from `tailscale file cp --targets`; **no tailnet permission changes**
  are made to make a destination appear.

---

## Fallback: private request file (only if `msg` payload can't be made reliable)

- Path: `<state dir or XDG_RUNTIME_DIR>/noctalia-taildrop/<requestId>.json`, mode `0600`,
  owned by the invoking user, max 8 KiB, exactly one JSON object.
- Helper writes the file, then runs `noctalia msg plugin … all taildrop_send '<requestId>'`
  (bare event, no payload). The service reads the file, checks owner + size, validates,
  then deletes it.
- **Recommendation:** keep as a fallback. The JSON-over-IPC path is simpler and already
  exercised by the platform, so prefer it unless live testing shows a parsing problem.

---

## Open questions — status

- **Task 0 (payload decoding) — RESOLVED.** Confirmed against the installed daemon:
  `noctalia msg plugin … all taildrop_send '<json>'` delivers the JSON object to `onIpc`
  as a decoded table. The service keeps a decode guard for the string-arrival case.
- **Service opens its own panel — CONFIRMED** via `noctalia.togglePanel`.
- **`<target>:` hostname — CONFIRMED** (reaches the address/permission layer).
- **Prerequisite / blocker:** `tailscale file cp` needs the local daemon operator set to
  the current user; one-time `sudo tailscale set --operator=ian`.
- **Directories / remote paths:** rejected (regular files only for the MVP).
- **HyprFM `types`:** `["*"]`; a multi-select spawns a helper per file (documented).
- Confirm `noctalia.togglePanel` from a service reliably brings the panel forward (not
  just toggling it off if it was already open) so a send flow isn't interrupted.
- Confirm `tailscale file cp <target>:` accepts the hostname emitted by `--targets`
  (live test at send time; it should, given the `--targets` output format).
- Decide whether `paths` should exclude directories or support them; Taildrop can send
  folders, but the HP plan's MVP is one regular file.
- Settle the `types` filter for the HyprFM action (`"*"`, `"dir"`, or a MIME pattern)
  and how a directory or remote/rclone URI is surfaced to the user.

---

## Related

- Plugin plan: `plan-tailscale-taildrop.md`
- HyprFM plan: `hyperfm-taildrop/plan-hyprfm-taildrop.md`
- HyprFM behavior that shapes this (verified in `fileoperations.cpp`): the context menu runs
  the action **once per selected file**, passes one path via `%f` as a discrete argv
  element (no shell), `%F` is equivalent to `%f`, and the process is detached.
