# Presets — implementation plan

Status: **built.** Kept as the design record; see SPEC.md section 13 for
what shipped and where it differs from this plan.

Two independent preset lists, mirroring the window's existing split by scope:

| List | Lives in | Captures | Applies to |
|---|---|---|---|
| **Framing presets** | right panel | ratio, fit, border, frame colour | the selected photo(s) |
| **Output presets** | batch panel, left column | width, quality, sharpening, destination, filename template, collision policy | the whole run |

This follows Lightroom's split between *develop* presets (the look) and
*export* presets (output settings), which maps onto our two scopes almost
exactly. Keeping them separate means choosing a look can never silently
redirect where files are written — the failure mode that loses work.

Starting empty: no seeded starter presets. No import/export for now (the JSON
is copyable by hand if it is ever needed).

---

## 1. A symmetry-enabling refactor first

`Framing` is already a self-contained, serialisable value object. The batch
output settings are not — they are loose fields on `Settings`. Extracting them
makes both preset types *the same shape*, so one generic store serves both
instead of two bespoke implementations.

```
OutputSettings:            # new, extracted from Settings
    output_width, quality, sharpen,
    dest_mode, dest_folder, template, collision

Settings:
    framing: Framing               # inherited by newly added photos
    output:  OutputSettings        # the batch
    custom_name, show_grid_overlay, last_open_dir
```

**`custom_name` stays out of `OutputSettings`,** and therefore out of presets.
It is content, not configuration — "iceland" belongs to today's batch, not to
a reusable preset. A preset carrying the template `{custom}_{n:03}` is useful;
one that also overwrites the name you just typed is not.

`show_grid_overlay` and `last_open_dir` are view state, excluded for the same
reason.

**Migration:** existing `settings.json` files have these keys flat at the top
level. `Settings.from_dict` must accept both shapes, nesting the flat form.
One branch plus a regression test, matching the one already covering files
written before `framing` moved onto the photo.

Touches `settings.py`, `pipeline.py` (`settings.output_width` becomes
`settings.output.output_width`), `BatchPanel`, and the tests that name those
fields. Mechanical, but it is the bulk of the diff.

---

## 2. Storage

One file, `presets.json`, beside `settings.json` in the existing config
directory:

```json
{
  "version": 1,
  "framing": [{"name": "Gallery mat 3:4", "values": {...}}],
  "output":  [{"name": "Web export",      "values": {...}}]
}
```

Separate from `settings.json` because it has a different lifecycle, it is the
thing you would back up or copy between machines, and a corrupt presets file
must not take your settings with it.

Stored as JSON rather than one file per preset, which means **preset names
need no filesystem sanitising** — any name the user types is safe.

Written through immediately on every change (add/update/rename/delete), reusing
the existing atomic write-then-replace, so a crash cannot lose a preset that
appeared to save.

```
PresetStore(path, section, factory)
    .all() .get(name) .add(name, values) .update(name, values)
    .rename(old, new) .delete(name)
```

One class, instantiated twice — once per section — with `factory` turning a
dict back into `Framing` or `OutputSettings`.

---

## 3. UI

A single reusable `PresetBar` widget, placed at the top of both panels:

```
Preset  [ Gallery mat 3:4 ▾ ]  [ Save… ]  [ ⋯ ]
```

- **Combo** lists `— none —` plus the saved presets.
- **Save…** names the panel's current values.
- **⋯** menu: Update, Rename…, Delete.

It emits intent (`applyRequested`, `saveRequested`, `updateRequested`,
`renameRequested`, `deleteRequested`) and owns no logic, so the two panels wire
it to their own state.

**The modified indicator matters.** Once you tweak a control after choosing a
preset, the combo must read `Gallery mat 3:4 (modified)`. Without it the
control claims a preset is applied when it is not. Detected by comparing the
panel's current values against the selected preset's — dataclass equality, with
`border_pct` rounded to one decimal to match the spinbox's own quantisation.
*Update* is enabled only while modified.

**Applying:**
- A framing preset goes through the existing edit path, so it lands on the
  current selection and multi-select and *Apply to all* keep working unchanged.
  With nothing selected it sets the value new photos inherit, consistent with
  how the panel already behaves.
- An output preset applies to the batch immediately, since that is its only
  scope.

Guard the combo's programmatic updates with the `_loading` flag both panels
already use, or selecting a preset will re-emit `changed` and fight itself.

---

## 4. Edge cases to handle explicitly

| Case | Behaviour |
|---|---|
| Corrupt or unreadable `presets.json` | Both lists empty, warning logged, app still starts |
| Framing preset naming a ratio that no longer exists | `Framing.normalized()` falls back; preset is not lost |
| Preset border above the 15% UI cap | Clamped on apply, as any other value is |
| Output preset whose `dest_folder` no longer exists | Apply everything else, clear the path, say so in the status bar. Process is already disabled with an explanatory tooltip when the folder is blank |
| Duplicate name on save | Offer to overwrite |
| Empty or whitespace-only name | Rejected |
| Very long name | Elided in the combo, full text in the tooltip |

---

## 5. Tests

**Core**
- Round-trip of both sections
- Missing file → empty; corrupt file → empty, no raise
- add / update / rename / delete
- Duplicate name rejected; blank name rejected
- A framing preset with a stale ratio normalises on load
- Atomic write leaves no `.tmp` behind
- `version` is written
- A pre-refactor `settings.json` with flat output keys still loads

**GUI**
- Save creates the preset and selects it
- Selecting a framing preset applies it to every selected photo, not just one
- Editing afterwards shows `(modified)`; Update clears it
- Delete removes it and falls back to `— none —`
- An output preset applies width, quality, sharpening and template
- An output preset with a missing folder degrades gracefully and leaves Process
  disabled
- Presets survive a restart

---

## 6. Order of work

1. Extract `OutputSettings`, migrate `Settings.from_dict`, update `pipeline`
   and `BatchPanel`. Green tests before touching presets.
2. `core/presets.py` + core tests.
3. `PresetBar` widget; wire into `FramingPanel`.
4. Wire into `BatchPanel`.
5. GUI tests, refresh the screenshot, rebuild the exe.

Roughly `core/presets.py` (~130 lines), `gui/preset_bar.py` (~110), panel
wiring (~60 across both), plus the refactor and about 20 tests. The image
pipeline is untouched throughout.
