# osd-notification

Cross-platform, network-triggerable On-Screen Display notification tool.

- Frameless, animated Qt notification widget (fade in/out, auto-sizing, screen-edge positioning)
- Threaded **GNTP/1.0 TCP** server and **JSON UDP** server, size-capped and payload-validated
- Typed, validated, self-healing INI configuration (auto-repairs missing keys, clamps out-of-range values)
- `NotificationClient` library with retry/backoff for sending notifications from other processes
- Path-traversal-safe icon resolution (icons must resolve inside an allow-listed directory)
- Production CLI: `osd-notification`

## Install

```bash
pip install osd-notification
#or
pip install -e .[pretty,dotenv]
```

## CLI usage

```bash
# Show config file path
osd-notification -c

# Show all config values (secrets masked)
osd-notification -c -s

# Get one value
osd-notification -c notification timeout

# Set one value
osd-notification -c notification timeout 5000

# Local demo notification (no server)
osd-notification -t

# Start GNTP (TCP) + UDP servers, blocks until Ctrl+C
osd-notification --server

# Start with a system tray icon (test notification, start/stop server, open config, quit)
osd-notification --tray

# Combine: tray icon + servers running from launch
osd-notification --server --tray

# Send a notification to a running server
osd-notification --send --title "Build Successful" --text "All tests passed." --transport udp

# Enable Windows-style cascading, then send several — they'll spread diagonally, not overlap
osd-notification -c notification position auto
osd-notification --send --title "One" --text "first"
osd-notification --send --title "Two" --text "second"

# Immediately close every currently visible notification
osd-notification --dismiss-all
```

## Library usage

```python
from osd_notification import NotificationClient

client = NotificationClient(host="127.0.0.1", udp_port=23064)
client.send(title="Build Successful", text="All unit tests passed.", icon="icon.png")
```

```python
from osd_notification.app import OSDApplication

app = OSDApplication()
app.start_servers()
app.run()
```

## Configuration

Config lives at `~/.osd-notification/osd-notification.ini` (Windows: `%USERPROFILE%\.osd-notification\osd-notification.ini`).

| Section        | Key                  | Default        | Notes                                   |
|----------------|----------------------|-----------------|------------------------------------------|
| `notification` | `position`            | `center_center` | one of 9 fixed screen positions, `auto` to cascade like Windows' default window placement, or `random` to scatter anywhere on screen |
| `notification` | `auto_anchor`          | `bottom_right`  | corner the cascade starts from when `position = auto` |
| `notification` | `stack_gap`            | `30`            | diagonal px offset per notification in `auto` mode (cascade step) |
| `notification` | `opacity`              | `0.95`          | clamped to `[0.05, 1.0]`                 |
| `notification` | `timeout`              | `3000`          | ms, clamped to `[0, 60000]`              |
| `notification` | `sticky`               | `False`         | overridden per-notification              |
| `notification` | `margin`               | `20`            | px from screen edge                      |
| `appearance`   | `font_family`          | `Consolas`      |                                           |
| `appearance`   | `char_size`            | `64`            | clamped `[8, 200]`                       |
| `appearance`   | `bg_color`             | `#1E1E2E`       | validated hex color                      |
| `appearance`   | `text_color`           | `#CDD6F4`       | validated hex color                      |
| `appearance`   | `border_color`         | `#89B4FA`       | validated hex color                      |
| `server`       | `enabled`              | `False`         | auto-starts servers if true              |
| `server`       | `gntp_port`            | `23053`         |                                           |
| `server`       | `udp_port`             | `23054`         |                                           |
| `server`       | `host`                 | `127.0.0.1`     |                                           |
| `server`       | `max_payload_bytes`    | `65535`         | UDP receive cap                          |
| `server`       | `allowed_icon_dirs`    | `` (empty)      | `os.pathsep`-separated; CWD always allowed |
| `window`       | `base_width`           | `240`           | default window width, px                |
| `window`       | `base_height`          | `240`           | default window height, px                |
| `window`       | `min_width`            | `240`           | floor for text-driven auto-resize        |
| `window`       | `max_width`            | `380`           | ceiling for text-driven auto-resize      |
| `window`       | `max_height`           | `600`           | ceiling for wrap-driven height growth    |
| `window`       | `text_padding`         | `40`            | px added to measured subtitle width      |
| `window`       | `extra_height`         | `40`            | extra breathing-room padding once text actually wraps to 2+ lines |
| `window`       | `icon_max_width`       | `160`           | default icon scale-to width, px          |
| `window`       | `icon_max_height`      | `140`           | default icon scale-to height, px         |
| `window`       | `soft_wrap_chars`      | `30`            | max unbroken (no-space) run length before a soft break point is inserted |
| `tray`         | `enabled`              | `True`          | show a system tray icon on `--tray`      |
| `tray`         | `icon_path`            | `` (empty)      | custom tray icon file; falls back to a generated dot icon |
| `tray`         | `tooltip`              | `OSD Notification` | tray icon hover tooltip                |
| `tray`         | `notify_on_server_toggle` | `True`       | show a native balloon when start/stop is clicked |

### System tray

`--tray` adds a `QSystemTrayIcon` with a context menu:

- **Show Test Notification** — also triggered by left-click/double-click on the icon
- **Start Server / Stop Server** — toggles the GNTP/UDP servers at runtime, label updates live
- **Dismiss All Notifications** — instantly closes every currently visible notification
- **Open Config File** — reveals the config directory in the OS file manager
- **Quit** — cleanly shuts down servers and the tray before exiting

If no `icon_path` is set (or the file is missing/invalid), a small filled-circle icon is
generated in-memory using the configured `appearance.border_color`, so the tray works with
zero bundled assets. On a session with no system tray (e.g. some headless Linux setups),
`--tray` logs a warning and the app continues without one rather than crashing.

### Auto-position cascading (like Windows' default new-window placement)

By default (`position = center_center`, or any other fixed value) every notification is its
own window placed at the exact same spot — sending several at once means they land right on
top of each other. Set `position = auto` and each new notification instead cascades
diagonally across the available screen from a starting corner (`auto_anchor`) — the same
placement Windows uses for new windows (e.g. opening several `cmd.exe` windows with default
placement), spreading them out rather than piling them in one line:

```bash
osd-notification -c notification position auto
osd-notification -c notification auto_anchor bottom_right   # starting corner: top_left, top_right, bottom_left...
osd-notification -c notification stack_gap 30                 # diagonal px offset per notification
```

The cascade steps diagonally away from `auto_anchor`'s corner, wrapping back to the start
once it would run off the opposite edge of the screen — and once every notification has been
dismissed, the next one starts back at the anchor corner instead of continuing to creep
across the screen. Dismissing one notification does **not** move the others (matches real OS
window cascading: closing one `cmd.exe` window doesn't reposition the rest).

If you don't want a repeating path at all — just spread anywhere on the monitor — use
`random` instead:

```bash
osd-notification -c notification position random
```

Each notification lands at a genuinely random spot on the available screen (respecting
`margin`), trying several candidate positions and picking whichever overlaps least with
notifications already visible — so repeated notifications actually spread across the whole
monitor rather than following any fixed diagonal or always starting from the same corner.

### Dismissing notifications immediately

```bash
osd-notification --dismiss-all
```

Sends a small control message over the same UDP channel notifications use (distinct from a
normal notification payload), telling the running server to close every currently visible
notification window right away — no fade animation, no waiting out the timeout. Requires a
server (`--server` or `--tray` with servers running) to already be listening; it's the same
requirement as `--send`. Also available as "Dismiss All Notifications" in the tray menu.

### Long text / auto-wrap sizing

The window height is computed from the *actual* wrapped-text bounding box at
the resolved window width (via `QFontMetrics.boundingRect` with
`Qt.TextWordWrap`), not a flat size bump — so text longer than one line grows
the window to fit instead of being clipped, up to `window.max_height`. Text
that fits on a single line never grows past `window.base_height`.

Qt's word-wrap only breaks at existing whitespace. A single unbroken "word"
longer than the window — a long URL, base64, a run of repeated characters —
has nowhere to break and will overflow the window no matter how tall it is.
Any run of non-whitespace longer than `window.soft_wrap_chars` (default 30)
gets invisible zero-width-space break points inserted so it can still wrap;
short/normal text is left completely untouched.

To preview specific text locally with no server involved (useful for
checking wrapping behavior, or to rule out a stale/already-running server
process as the cause of unexpected output):

```bash
osd-notification --test --title "Build Successful" --text "your long text here"
```

### Fixing a stale config after an update

Config auto-migration only *adds missing keys* — it never overwrites ones
that already exist. If you upgrade and a section (e.g. `[window]`) still has
old/conflicting values from a previous version, reset just that section:

```bash
osd-notification --reset-config window   # reset one section to defaults
osd-notification --reset-config          # reset every section
```

## Security notes

- Icon references from the network are resolved with `resolve_icon_path`, which rejects
  anything outside `allowed_icon_dirs`, non-image extensions, or non-existent files —
  this closes the path-traversal hole present in a naive `os.path.exists(icon)` check.
- UDP/TCP payloads are size-capped and run through `NotificationPayload` validation
  (title/text length limits, timeout bounds) before they ever reach the GUI.
- Secret-looking config keys (`token`, `password`, `client_id`, `client_secret`) are
  masked in `--show` output.

## Development

```bash
pip install -e .[dev]
pytest
```

## 👤 Author
        
[Hadi Cahyadi](mailto:cumulus13@gmail.com)
    

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/cumulus13)

[![Donate via Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/cumulus13)
 
[Support me on Patreon](https://www.patreon.com/cumulus13)
