# Monitor Control

Monitor Control is a modern GNOME application for controlling external monitors via DDC/CI using `ddcutil`.

## Current state

This repository contains the initial scaffold for:

- `Adw.Application`-based GTK4/libadwaita app
- MVC-inspired structure
- Backend abstraction (`MonitorBackend`) with `DdcutilBackend` implementation
- Debounced live sliders for monitor controls
- Toast-based user-facing error handling

## Project structure

```text
monitor-control/
├── assets/
├── desktop/
├── screenshots/
├── src/
│   ├── __init__.py
│   ├── constants.py
│   ├── main.py
│   ├── monitor.py
│   ├── utils.py
│   ├── widgets.py
│   └── window.py
├── tests/
├── LICENSE
├── pyproject.toml
└── requirements.txt
```

## Requirements

- Python 3.13+
- GTK4 + libadwaita runtime
- `ddcutil`
- DDC/CI enabled in monitor OSD

### Fedora setup

```bash
sudo dnf install -y python3-gobject gtk4 libadwaita ddcutil
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
```

## Run

```bash
source .venv/bin/activate
python -m src.main --debug
```

## Logging

Logs are written to:

`~/.local/share/monitor-control/logs/monitor-control.log`

## Notes

- The UI layer is backend-agnostic and does not invoke `ddcutil` directly.
- Monitor commands use `Gio.Subprocess` for GNOME main-loop-friendly async execution.
- We rely on distro-provided PyGObject packages instead of pip-built wheels for reliable setup.

_This project was vibe coded using github copilot._  
Made with love in the Himalayas 🏔️🇳🇵
