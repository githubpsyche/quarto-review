# Changelog

## 0.2.1 — 2026-09-29

- Browse matching comments and changes in an independent HTML review list, with explicit navigation back to a passage.
- Filter authors' pending edits, inspect settled change alternatives, and keep fragmented inline edits readable without redundant markers.
- Default to comments and changes with open comments and pending changes selected; translate corresponding status filters when changing review type.
- Keep empty navigation anchors out of ordinary wording changes while still tracking nearby prose edits.
- Document a complete explicit return-review example, installation effects, upgrades, removal and the limits of simultaneous source writers.
- Run browser checks, the explicit review round and isolated wheel rendering alongside source tests in CI; pull requests do not deploy Pages.
- Display demo build provenance and align package, module and extension version declarations.

A complete synthetic schema-2 review cycle passed in Word for Mac 16.113.2, including acceptance, rejection, reply, resolution, explicit return reconciliation, a retained local edit and another Word save.
Word rounds pending revision timestamps to minutes; comment and reply timestamps were unchanged in this check.
See [release evidence](docs/release.md) for automated checks, skipped coverage and limits.
