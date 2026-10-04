# An iPhone version: plan

Status: **a proposal. Nothing here is built.**

The Android app is written with BeeWare (Briefcase and Toga), which also
builds for iPhone from the same project. So an iPhone version would not be a
second app. It would be the same app, with the parts that talk to Android
replaced by parts that talk to iOS.

---

## 1. What carries over unchanged

About two thirds of the phone app never touches Android and would run on an
iPhone as it stands:

| Shared | What it is |
|---|---|
| `igprep/core` | The image pipeline: geometry, placement, rendering, preview. Also the desktop app's. |
| `framing.py` | Framing one photo; previews; output names. |
| `gestures.py` | Turning finger positions into drags and pinches. |
| `entries.py` | What counts as a photo; the order of a listing; what is checked. |
| `thumbs.py` | Fetching thumbnails a few at a time for what is on screen. |
| `places.py`, `views.py` | Remembering the folders, the tiles-or-list choice, the divider. |
| `words.py`, `icons.py` | What the app says; its icons, drawn in code. |
| `phonelog.py` | The log, apart from where its file is kept. |
| `app.py`, `browser.py` | The two screens and how they behave, written against Toga. |

## 2. What has to be written again

Six modules talk to Android. Each does one job, and each would need an iOS
twin that does the same job through Apple's interfaces.

| Android module | Its job | On iOS |
|---|---|---|
| `storage.py` | Folder access that lasts; listing; creating; reading and writing files; thumbnails; saving to the gallery | The Files folder picker with saved bookmarks; `FileManager`; Quick Look thumbnails; the Photos library |
| `androidimage.py` | Decoding a photo into sRGB | Image I/O, or the image library itself if its iOS build can convert colour |
| `filelist.py` | The scrolling list and tiles | `UITableView` and `UICollectionView` |
| `touch.py` | Fingers on the preview; fast redraw | Touch events on a `UIView`; a `CGImage` drawn directly |
| `androidui.py` | Icons in buttons, the name pop-up, brief messages, the path line, the drag handle, menu outline, Back, returning to the app | The UIKit equivalent of each; Back has no equivalent and is simply absent |
| `androidlog.py` | Where the log file lives | The app's Documents folder, shown in the Files app |

`selftest.py`, the emulator driver and the build workflow are also
Android-specific and would each need a counterpart.

## 3. Things that are different on an iPhone, not just renamed

These are the open questions. Each is the kind that cost a build or two to
settle on Android.

- **Getting it onto the phone.** Android installs a downloaded file. An
  iPhone does not. The choices are a paid Apple developer membership (builds
  then arrive through TestFlight and last 90 days each), or a Mac with Xcode
  and a cable (free, but each install stops working after 7 days). Either
  way the build itself needs a Mac, which GitHub's build machines can supply.
- **Where photos live.** On Android, photos are files in folders. On an
  iPhone they are in the Photos library, which is not a folder. The input
  side would probably need to browse the Photos library as well as, or
  instead of, a folder.
- **Whether Google Drive hands over folders.** Proton Drive did not on
  Android. On iOS it depends on each storage app in the same way, and has to
  be tried.
- **Colour conversion.** Android's own decoder was needed because the image
  library's Android build cannot convert colour. Whether its iOS build can
  has to be checked on a device.

So the first iPhone build should be what the first Android builds were: a
test app that answers these, before any screen is written.

## 4. The larger change this suggests

Today the Android modules sit beside the shared ones in one folder, told
apart by name and by a line in each one's opening comment. That is enough
for one platform. For two, the proposal is:

```
phone/src/igprepper/
    app.py, browser.py, framing.py, ...   shared
    platform/__init__.py                  chooses android or ios at launch
    platform/android/                     storage, image, filelist, touch, ui, log
    platform/ios/                         the same six, for iOS
    platform/fake/                        the same six, pretending, for tests
```

- The shared modules would import from `platform` and nothing else. Whatever
  `platform/android` offers, by name, is the exact list of what
  `platform/ios` has to offer too.
- The `fake` platform is the part worth having even without iOS. The two
  screens (`app.py`, `browser.py`) cannot be run on a desktop today, because
  they need Android; they are tested only in the emulator, which takes ten
  minutes a run. With a pretend platform they could be tested here in
  seconds.

It changes no behaviour, but it moves six files and touches every import,
and it needs one full emulator run to prove. It is best done either now, as
a step of its own, or as the first step of the iOS work. It should not be
mixed with any other change.

## 5. Keeping the two in step afterwards

- One project, one version number: a `phone-N` tag builds both.
- Behaviour lives in the shared modules, so a change made there reaches both.
  A change that needs something new from the platform means adding it to
  both platform folders; the build for whichever was forgotten fails at
  import, which is the reminder.
- The self-test's steps (choose folders, check photos, frame, save) are the
  same on both. Only how it presses things differs.
