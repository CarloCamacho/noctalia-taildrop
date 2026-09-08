# Changelog

All notable changes to this plugin are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/); this project adheres to
[Semantic Versioning](https://semver.org).

## [1.0.0] - 2026-09-08

Initial release, merged into the Noctalia community plugin store.

### Added

- Send a file (or folder — auto-archived to `<name>.tar.gz` in a private temp dir) to any device
  on your tailnet from a file-manager right-click menu.
- Focused send dialog (`panel: send`) that lists eligible Taildrop destinations from
  `tailscale file cp --targets`, online first.
- `service` that validates a send request (absolute paths, bounds, files/folders), coalesces
  concurrent once-per-file invocations into one dialog, runs `tailscale file cp`, and reports the
  result.
- **Retry** on failure (re-sends the same files to the same destination) and auto-close after a
  successful send.
- Bridge helper (`bin/noctalia-taildrop`) that validates paths, dispatches the request, and opens
  the dialog via the non-toggle `noctalia msg panel-open`.
- HyprFM / Nautilus / Dolphin / Thunar integration samples under `integration/`.
- Store thumbnail (`thumbnail.webp`) and plugin page (`README.md`).
