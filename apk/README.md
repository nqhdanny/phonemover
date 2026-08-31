# PhoneMover Importer (Android helper APK)

HUAWEI-side helper that imports contacts (`contacts.vcf`) and calendar events
(`calendar.ics`) into the system providers. The Windows host pushes files via
`adb` and triggers import with a broadcast.

## Build

```bash
export ANDROID_HOME=/path/to/android-sdk
gradle assembleDebug
# output: app/build/outputs/apk/debug/app-debug.apk
```

Requires: JDK 17, Gradle 8.x, Android SDK (compileSdk 36).

## How the host drives it

```bash
# 1. install once
adb install -r app-debug.apk

# 2. push data
adb shell mkdir -p /sdcard/PhoneMover
adb push contacts.vcf /sdcard/PhoneMover/contacts.vcf
adb push calendar.ics /sdcard/PhoneMover/calendar.ics

# 3. trigger import (result code + count returned)
adb shell am broadcast -a com.phonemover.importer.IMPORT \
    --es type contacts --es path /sdcard/PhoneMover/contacts.vcf
adb shell am broadcast -a com.phonemover.importer.IMPORT \
    --es type calendar --es path /sdcard/PhoneMover/calendar.ics
```

## Permissions

- READ/WRITE_CONTACTS — insert contacts
- READ/WRITE_CALENDAR — insert calendar events
- READ_EXTERNAL_STORAGE (≤ Android 12) — read pushed files

> EMUI/AOSP may require granting these at runtime or via `adb shell pm grant`.
