# PhoneMover

Open-source, non-commercial tool to transfer personal data from iPhone to HUAWEI (EMUI/AOSP) phones via USB cable.

**Languages:** English · Русский

> ⚠️ **DISCLAIMER**: This is an unofficial, non-commercial, open-source project with **no affiliation to Apple Inc. or Huawei Technologies**. Provided **AS-IS** with no warranty of any kind. Use at your own risk. See [DISCLAIMER.md](DISCLAIMER.md) for full terms.

## Features

- Transfer **Contacts, Photos, Videos, Music, Calendar, Reminders, Bookmarks,
  Notes** from iPhone to HUAWEI via USB (offline, no cloud)
- No iTunes required (pure open-source stack: pymobiledevice3)
- English / Russian UI
- MTP / adb push for media + companion APK for system data (contacts/calendar)
- **Notes land inside the HUAWEI Notepad app**, not just as a file on the device

## Notes → HUAWEI Notepad

HUAWEI Notepad (`com.huawei.notepad`) is a `/system/priv-app` system app with
**no public import API**. Everything convenient is locked down:

| Attempted channel | Result |
|---|---|
| read `/data/data/com.huawei.notepad/` | `Permission denied` (even for adb shell) |
| `adb backup` / `bmgr` | app does not declare `allowBackup` |
| `run-as` | `not debuggable` |
| ContentProvider `notepad-app.com` | signature permission `HW_SIGNATURE_OR_SYSTEM` |
| deep link `hwnotepad://note_new` | same signature permission |
| `VIEW` a `*.hdoc` file | resolves to `SketchActivity` (handwritten notes), plain text fails |

What works is the app's **`ACTION_SEND` handler**. `NotePadShareActivity`
registers `android.intent.action.SEND` for `text/plain` and shows a
"Save as new note" dialog pre-filled with the shared text:

```bash
adb shell 'am start -a android.intent.action.SEND -t text/plain \
  --es android.intent.extra.TEXT "$(echo <base64> | base64 -d)" com.huawei.notepad'
```

Each note is sent one at a time, **SAVE** is tapped automatically (button
coordinates scaled from a 1320x2856 reference to the device's real size), and
the note is confirmed created when `NoteEditor` reaches the foreground.

Notes are base64-encoded for transport: `adb shell` joins its arguments into a
string handed to `/system/bin/sh`, so a newline inside a note would otherwise
split the command in two (observed as `sh: IIh: inaccessible or not found`).

Verified on a real HUAWEI CRS-LX9 (EMUI 16 / Android 16, Notepad 14.6.9.300).

## Architecture

```
core/
  models.py        data type registry (8 types)
  manifest.py      unified lookup inside an iOS backup (Manifest.db)
  device.py        iPhone detection (pymobiledevice3)
  backup.py        backup engine (wraps pymobiledevice3 CLI)
  engine.py        MigrationEngine: backup -> parse -> write pipeline
  parse/           contacts -> vCard, calendar -> .ics, notes -> .txt/.json,
                   bookmarks -> HTML, reminders -> VTODO, photos/media extract
  write/
    adb_import.py  push + trigger the importer APK (contacts/calendar/reminders)
    notepad_import.py  ACTION_SEND notes into HUAWEI Notepad, one per note
    huawei.py      orchestration: detect device, install APK, run each channel
    mtp.py         media copy
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

🚧 **Under active development** — all 8 data types are implemented and
unit-tested (33 tests); validated end-to-end on a real HUAWEI CRS-LX9
(EMUI 16 / Android 16) with a real iOS 17 backup.

## License

MIT — see [LICENSE](LICENSE).
