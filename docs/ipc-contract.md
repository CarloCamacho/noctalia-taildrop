# Taildrop IPC Contract

> The interface between the **Taildrop plugin** (`carlocamacho/taildrop`) and
> external callers (file managers). It is intentionally small: one request, one
> shared job, and a handful of actions.

## Transport

### Bridge helper → service (one call, no shell)

```sh
noctalia msg plugin carlocamacho/taildrop:service all taildrop_send '<json>'
```

The bridge helper (Python) builds `json` with `json.dumps(...)` and passes it as
a single argv element via `subprocess.run([...], shell=False)`. Noctalia decodes
it into `payload`.

### Bridge helper → open the dialog

```sh
noctalia msg panel-open carlocamacho/taildrop:send
```

`panel-open` is a **non-toggle** open: it opens the dialog if it is closed and
brings it forward if it is already open. This is deliberate — the plugin service
does **not** call `noctalia.togglePanel` (the only panel call available to
plugins), which would close an already-open dialog.

### Event name

`taildrop_send` — namespaced to avoid colliding with anything else in the
plugin's `onIpc` (there is nothing else in this plugin, but it keeps the contract
extensible).

---

## Request schema (bridge → service)

Delivered as `onIpc("taildrop_send", payload)` where `payload` is the decoded
table.

| Field | Type | Rules |
| --- | --- | --- |
| `v` | int | `= 1` (contract version) |
| `requestId` | string | ASCII `[A-Za-z0-9._-]`, length 1..64, unique per request; correlation only |
| `paths` | string[] | 1..32 entries; each an **absolute**, **regular-file** path, ≤4096 bytes |
| `origin` | string (optional) | informational, not trusted (bridge sends `"file_manager"`) |

**Bounds (validated in the service):** `paths` count ∈ `1..32`, total JSON ≤ 8 KiB.
Reject anything outside these limits without opening a dialog.

---

## Transfer job (shared state, key `taildrop_transfer`)

The service writes a shared job that the dialog watches.

| Field | Type | Notes |
| --- | --- | --- |
| `requestId` | string | echo from the request |
| `paths` | string[] | validated absolute paths |
| `target` | string | `""` until the user picks; then `<hostname or ip>` |
| `phase` | enum | `choosing` \| `confirming` \| `sending` \| `succeeded` \| `failed` \| `cancelled` |
| `status` | string | human status line |
| `error` | string | populated on `failed` |
| `eligible` | array | `tailscale file cp --targets`: `{name, ip, online}` |
| `createdAt` / `updatedAt` | number | epoch seconds |
| `revision` | number | bumped on every write so the dialog can detect change |

---

## Flow

1. **Bridge** validates each path (absolute, exists, is a regular file, readable).
   Paths are never placed on a shell command line.
2. Bridge builds the request JSON and calls `noctalia msg plugin … all taildrop_send '<json>'`,
   then `noctalia msg panel-open …` to surface the dialog.
3. **Service** `onIpc("taildrop_send", payload)`:
   - Decode `payload` if it arrives as a string (`noctalia.json.decode`).
   - Validate fields and bounds; on failure notify and **do not** touch the dialog.
   - If an active job is still `choosing`/`confirming` and was created within the
     last 2 seconds, **coalesce**: merge the new paths in and refresh state (this
     turns a file manager that fires once-per-file into one dialog). Otherwise
     start a fresh job and fetch eligible targets from `tailscale file cp --targets`.
4. **Dialog** watches `taildrop_transfer`. If a job is active it renders the file
   list + eligible destinations. The user selects a destination → confirm/cancel.
5. **Confirm** → dialog sets `taildrop_command = { action = "taildrop_confirm", jobId, target }`.
6. **Service** `taildrop_confirm`:
   - Re-validate each path still exists; abort with a clear error otherwise.
   - Run `tailscale file cp <paths…> <target>:` as an argv vector (each element
     shell-quoted; no raw concatenation).
   - `phase=sending` → `succeeded`/`failed`; notify; bump `taildrop_transfer`.
7. **Cancel** → `phase=cancelled`; **Done** → `phase` cleared (job emptied) and
   the dialog closes.

---

## Security invariants

- **No shell** anywhere: the bridge uses `subprocess` with an argv list; the
  service builds argv with `shellQuote`/`shellCommand` and `noctalia.runAsync`.
- Paths are **data**, never interpolated into a command string.
- Payload is bounded; non-table / over-limit / non-absolute / non-regular-file
  requests are rejected without side effects.
- `requestId` is charset/length-validated and used only for correlation.
- Eligibility comes from `tailscale file cp --targets`; no tailnet permission
  change makes a destination appear.

---

## Environment note

`tailscale file cp` requires the local user to be the daemon **operator**. If a
send fails with `Access denied: file access denied`, run once:

```sh
sudo tailscale set --operator=$USER
```

This is a local daemon setting; it does not change tailnet policy.

---

## Open questions / notes

- **`noctalia.togglePanel` toggles closed.** Verified empirically (only
  `noctalia.togglePanel` exists in the plugin API — `openPanel`/`closePanel` are
  not exposed). The bridge therefore uses the CLI `noctalia msg panel-open`, which
  is non-toggle.
- **Directories are rejected** (`tailscale file cp` is files-only). A future v2
  could archive-on-send (`folder.tar.gz`).
- **One dialog per burst.** The 2s coalescing window merges concurrent
  once-per-file invocations. A file manager that passes all selected paths in one
  invocation (Nautilus/Dolphin/Thunar) already yields a single request.
