# i18n

Qt Linguist translation files (`.ts` → `.qm`).

- `en.ts` — English (source language, default)
- `ru.ts` — Russian

All user-visible strings must be wrapped with `QCoreApplication.translate()` / `tr()` —
no hardcoded UI text (see ADR-004 in the project memory).
