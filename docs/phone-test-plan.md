# Phone test app: plan

Status: **planned, not built.**

A small Android app whose only job is to answer three questions before any
real phone app is written:

1. Can an app be delivered to the phone through GitHub alone?
2. Can it create folders and files in Proton Drive through Android's folder
   picker, and does Proton sync them?
3. Does the existing image pipeline (`igprep/core`) run correctly on a phone?

The app never creates or names folders on its own. Folder names are typed by
hand, because the photo library does not follow one naming convention.

---

## Delivery

- Lives in `phone/` in this repo and is built with BeeWare (Briefcase + Toga),
  importing `igprep/core` unchanged.
- GitHub Actions builds it and publishes it as a **pre-release**, so the
  Windows download stays the "latest" release.
- Installed by downloading the file on the phone from the releases page.
- Every build is signed with one fixed key, so each build installs over the
  previous one. Without that the phone refuses the update, and uninstalling
  would wipe the folder permission under test. The key is created by the repo
  owner, stored as a repository secret, and never committed.

## What a public build may contain

- Code from this repo and synthetic, generated test images. No personal photos.
- A signing certificate labelled only `Personal Apps`, and a package id of
  `org.igprepper.igprepper`. Both are readable by anyone who downloads the
  build, so neither carries a personal name.
- Nothing from the development PC: builds run on GitHub's machines.

The app uploads nothing itself. Files reach Proton Drive through the Proton
Drive app, and the log stays on the phone until it is shared by hand.

## The log

- Plain text, one new file per launch, in `Download/IGprepper/` on the phone,
  readable from the Files app.
- Written line by line, so a crash still leaves everything up to that point.
- Records: build version, Android version and phone model, each action and its
  result, timings, full error text, and the names of folders created through
  the app.
- Never lists what already exists in the Drive.

## The one screen

- **Choose folder**: opens Android's folder picker, where a Proton Drive
  folder is chosen and access granted.
- **Location**: shows where you are inside that folder, with its subfolders.
  Tap one to enter it; **Up** goes back.
- **New folder**: a name field and a Create button. Creates exactly the name
  typed, in the current location.
- **Write test files here**: creates the test files in the current folder.
- **Run image tests**: runs the pipeline checks on the bundled images.
- **Frame a photo**: pick from the gallery, frame it, save it here, and save a
  copy to the phone gallery.

---

## Test objectives

Each gate only matters if the one before it passes.

### Gate 1: delivery

1. GitHub builds an installable app from the repo.
2. It downloads from the releases page and installs.
3. A later build installs over it without uninstalling.
4. The log file appears in `Download/IGprepper/` and can be opened and shared.

### Gate 2: writing to Proton Drive

5. The folder picker opens and a Proton Drive folder can be chosen.
6. The log records what Proton says it allows: create, write, rename, move,
   delete.
7. A folder is created with a hand-typed name, including spaces and symbols.
8. A second folder is created inside the first.
9. Typing a name that already exists: the log records what Proton does.
10. **Write test files here** creates, in the current folder:
    - a small text file, read back and compared;
    - a real framed JPEG that can be opened in Proton Drive;
    - a file of about 20 MB, timed;
    - the same filename written twice, to see how Proton handles it.
11. Checked by hand in the Proton Drive app and on the PC: the folders and
    files appear, names intact, and the JPEG opens.
12. Access survives closing the app and restarting the phone, with no second
    trip through the picker.

### Gate 3: the image pipeline

13. The image library loads; the log records its version and whether
    colour-profile conversion is included.
14. `igprep/core` runs on a bundled image and passes the desktop checks:
    1080 x 1440, 43 px border, sRGB, 4:4:4.
15. A bundled image tagged with a non-sRGB profile converts to the same values
    the desktop produces.
16. A full-size gallery photo is processed without crashing; time is logged.

### Gate 4: end to end

17. A gallery photo is framed and saved into the current Proton folder.
18. The copy saved to the phone gallery is visible to Instagram.

### Gate 5: is the plain interface good enough

19. The preview appears and updates when a setting changes.
20. The controls are usable and readable in dark mode.

---

## If something fails

| Failure | Consequence |
|---|---|
| Gate 1 | Fix the build or signing first; nothing else can be tested |
| Objectives 7, 8 or 10 | Proton is read-only to other apps; phone organising is off, fall back to the desktop |
| Objective 12 | Usable, but the folder must be re-picked each session |
| Objective 13 or 15 (no colour conversion) | Let Android convert to sRGB before Python gets the photo |
| Objective 5 (picker workaround breaks) or Gate 5 | Native Android screen over the same Python code |

## Builds

1. **Build 1**: an empty app that writes a log file. Proves Gate 1 cheaply
   before anything else is written. Needs the signing key first.
2. **Build 2**: folder picker, location list, New folder, Write test files,
   Run image tests. Covers Gates 2 and 3, and proves updating over Build 1.
3. **Build 3**: Frame a photo, plus fixes from the first two logs. Covers
   Gates 4 and 5.

## Not in this test

iOS, presets, filename templates, organising original photos, and visual
polish.
