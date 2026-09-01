# OpenReel compatibility matrix

**Pinned revision:** `5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9`
**Last verified:** August 30, 2026

PBJ adopts OpenReel's project and tools as a whole. This matrix records which
representative behaviors have passed PBJ's required handoff, snapshot, restore,
render, receipt, and approval boundaries. It does not describe separate PBJ
implementations of those tools.

| Behavior | Editor operation | Snapshot/restore | Final MP4 | Approval/learning | Status |
|---|---|---|---|---|---|
| Supplied-media playback | Existing OpenReel playback | Passed | H.264/AAC, 1080×1920 | Passed | Verified |
| End trim | Native **Trim end to playhead** | 18.87s → 10.00s restored | 10.07s playable MP4 | One changed clip; −8.866667s | Verified |
| Split | Native **Split** at 5.00s | Two clips restored | 10.07s playable MP4 | 1 retained + 1 added clip | Verified |
| Ripple delete | Removed second 5s split | One 5s clip restored | 5.08s playable MP4 | Retained clip; −13.866667s | Verified |
| Timeline move | Native move path; start 0s → 1s | Exact 1.0s start restored | 3.58s MP4; 1.0s opening gap | One changed clip | Verified |
| Position transform | Native inspector, X = 80px | Exact value restored | Shift visible in 5.08s MP4 | One changed clip | Verified |
| Crop | Native square preset | Pixel-correct crop restored | Square crop visible in 5.08s MP4 | One changed clip | Verified |
| Speed | Native 2× preset | Speed 2; 2.50s restored | 2.58s playable MP4 | One changed clip | Verified |
| Volume/audio | Native 50% volume | Volume 0.5 restored | AAC retained; level reduced | One changed clip | Verified |
| Narrow layout | Preview and compact native timeline remain visible; fixed center playhead with padded timeline scrolling beneath it; Assets/Inspector open as sheets; contextual native clip tools sit at bottom | OpenReel project, time, and selection state are shared | Export action remains visible | No new evidence type | TikTok-inspired interaction implemented; device retest pending |
| Touch move and trim | Existing OpenReel clip operations through pointer events | Whole-project snapshot unchanged | Same OpenReel render path | No new evidence type | Implemented; device QA pending |
| Installed PWA shell | PBJ bypasses standalone desktop blocker; safe-area and dynamic viewport enabled | Same PBJ project identity | Export remains visible | No new evidence type | Implemented; device QA pending |
| Safari viewport chrome | Inline dynamic viewport overrides desktop fallback so controls/nav remain above browser chrome | No project change | Export remains visible | No new evidence type | First iPhone finding fixed; retest pending |
| Background interruption | Flush dirty OpenReel project on hidden/pagehide | Latest immutable snapshot remains recovery source | No render during interruption | Intermediate snapshot only | Automated recovery and lifecycle coverage passed; device QA pending |
| Home Screen relaunch | Resume last successfully loaded PBJ project on standalone launch only | PBJ revalidates session, permission, snapshot, and media | No export side effect | No learning side effect | Automated launch contract passed; device QA pending |
| Proxy memory loading | Sequential hydration of PBJ mobile-safe per-source proxies; abandoned loads abort | Same permitted media identities | Actual proxy byte sizes recorded | No learning side effect | Automated loader contract passed; device memory QA pending |

The verified trim walkthrough produced one project-scoped approved example and
one governed `approved_openreel_export` candidate. Reapproving the revised
project replaced the latest approved outcome instead of counting the same
project twice.

The native split walkthrough preserved the 10-second project duration, restored
two timeline clips after reopen, and rendered the same 10.07-second H.264/AAC
output duration. PBJ measured one retained initial clip, one added split clip,
and one changed clip without creating a second project-level positive example.

Ripple delete then removed the second five-second split and restored one
five-second clip after reopen. Its H.264/AAC output measured 5.08 seconds. A
subsequent native position transform persisted an exact 80-pixel horizontal
offset and the final MP4 visibly contained that shift.

The crop walkthrough exposed and corrected an upstream preset calculation that
had compared normalized percentages without accounting for source dimensions.
Square crop on 720×1280 media now persists as `y = 0.21875` and
`height = 0.5625`, restores after reopen, and is visible in final output.

The native 2× speed preset restored `speed = 2` and reduced the five-second
timeline to 2.50 seconds; the delivered MP4 measured 2.58 seconds. Native 50%
volume restored `volume = 0.5`, retained AAC audio, and reduced measured mean
and peak levels relative to the preceding 100% export.

Timeline move shifted the clip from 0 to 1.0 seconds through OpenReel's existing
move operation. PBJ restored the exact start time, and the 3.58-second MP4
contained the expected one-second opening gap. Option/Alt + Left/Right exposes
the same move operation in accessible 0.1-second steps; pointer dragging remains
OpenReel-native.

The current narrow-screen adaptation replaces the fixed 1,200+ pixel desktop
grid at widths through 767px with an iPhone-first short-form editing shell.
OpenReel's Preview and compact native Timeline remain visible together; its
existing Assets and Inspector panels open as dismissible sheets, and selection
reveals a bottom tray for the existing Split, Delete, Speed, Crop, and Volume
paths. The mobile playhead remains fixed at center while scrolling scrubs the
padded timeline beneath it; playback moves that same timeline under the fixed
cursor. The compact toolbar retains the project name and Export & Approve. This
is a presentation change over OpenReel's project state and commands, not a PBJ
editor or a set of duplicated editing features. Type-check and production build
pass; physical
OpenReel clip move and trim now use pointer events and wider narrow-screen trim
targets, so the same operations accept mouse, pen, and touch without a PBJ
command layer. Process-restart snapshot recovery passes automated coverage.
Pending edits also flush immediately when the browser backgrounds or hides the
page, with keepalive limited to safely sized requests. Physical iPhone touch,
orientation, keyboard, memory, interruption timing, and Home Screen PWA QA
remain pending.
