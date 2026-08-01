# Agent / contributor rules — AI Media Studio

## Hard rule: keep product docs in sync

**Always update these three files when behavior or UX changes** (user-visible features, models, Resolve, Library, cost labels, layout patterns, keys, install, version bumps):

| File | Role |
|------|------|
| **[README.md](README.md)** | Install, keys, tabs overview, Resolve path, Settings, sharing |
| **[FEATURES.txt](FEATURES.txt)** | Full capability inventory |
| **[RELEASE_NOTES.md](RELEASE_NOTES.md)** | What’s new by version (GitHub Releases) |

### When to update

- **New or changed capability** → FEATURES (detail) + README (if install/overview-worthy) + RELEASE_NOTES (bullet under current version)
- **Bugfix with user-visible impact** → RELEASE_NOTES; FEATURES/README only if documented behavior was wrong
- **Version bump** → `__version__` / `APP_VERSION` + new or updated section in RELEASE_NOTES
- **Docs-only PR** → still keep the three consistent with each other

### Do not

- Ship feature work with only code changes when users would rely on README / FEATURES / release notes
- Leave RELEASE_NOTES only for “big” releases — incremental product changes belong under the current version section

This rule applies to humans and coding agents in this repo.
