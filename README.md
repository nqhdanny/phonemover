# PhoneMover

Open-source, non-commercial tool to transfer personal data from iPhone to HUAWEI (EMUI/AOSP) phones via USB cable.

**Languages:** English · Русский

> ⚠️ **DISCLAIMER**: This is an unofficial, non-commercial, open-source project with **no affiliation to Apple Inc. or Huawei Technologies**. Provided **AS-IS** with no warranty of any kind. Use at your own risk. See [DISCLAIMER.md](DISCLAIMER.md) for full terms.

## Features (v1.0)

- Transfer **Contacts, Photos, Videos, Music, Calendar** from iPhone to HUAWEI via USB (offline, no cloud)
- No iTunes required (pure open-source stack: pymobiledevice3)
- English / Russian UI
- MTP for media + companion APK for system data (contacts/calendar)

## Architecture

```
core/
  models.py        data type registry (v1.0 = 5 types)
  manifest.py      unified lookup inside an iOS backup (Manifest.db)
  device.py        iPhone detection (pymobiledevice3)
  backup.py        backup engine (wraps pymobiledevice3 CLI)
  engine.py        MigrationEngine: backup -> parse -> write pipeline
  parse/           contacts -> vCard, calendar -> .ics, photos/media extract
  write/           MTP media copy + adb import (contacts/calendar)
gui/               PySide6 window (EN/RU, background worker)
i18n/              lightweight EN/RU translation (dict lookup)
apk/               Android helper APK (ImportReceiver)
tests/             unit tests (no device needed)
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests/          # run tests
python -m gui.main               # launch GUI
```

## Build Windows exe (GitHub Actions)

Push a `v*` tag (or run the workflow manually):

```bash
git tag v1.0.0 && git push origin v1.0.0
```

The `.github/workflows/build-windows.yml` builds a single `PhoneMover.exe`
(PyInstaller onefile + windowed) on `windows-latest` and uploads it as an artifact.

## Build Android helper APK

See [apk/README.md](apk/README.md).

## Project status

🚧 **Under active development** — v1.0 core + GUI + APK are implemented and unit-tested;
real-device validation (Proxmox USB passthrough) is the remaining integration step.

## License

MIT — see [LICENSE](LICENSE).
