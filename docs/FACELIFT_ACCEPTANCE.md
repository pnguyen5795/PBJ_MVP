# Troy Facelift Acceptance

**Branch:** `troy-facelift`  
**State:** Merge candidate awaiting physical-iPhone acceptance

## Verified before device review

- PBJ's canonical route order, real backend, privacy, learning, and OpenReel
  authority boundaries remain unchanged.
- Troy contributes presentation and approved artwork only. Studio, mock data,
  simulated rendering, Clerk authentication, alternate services, and alternate
  application state are excluded.
- Representative 375×667, 390×844, 430×932, and 844×390 browser layouts retain
  the mobile application presentation.
- PBJ tests, OpenReel tests, the OpenReel production build, and clean application
  of the PBJ patch to the pinned OpenReel revision pass.
- The Git branch contains no project media, private projects, provider keys,
  local `.env`, evaluation checkout, or installed dependencies.

## Physical-iPhone walkthrough

1. Start PBJ with `start_app.command` and open the displayed Wi-Fi address on
   the iPhone.
2. Confirm Access, Home, Projects, More, and the four New Project screens feel
   consistent in portrait and landscape. The old Home / Projects / More bottom
   bar must be absent, and no remaining control should sit under Safari's top or
   bottom chrome.
3. Add PBJ to the Home Screen, launch it there, rotate once in each direction,
   background it, and reopen it. Authorization should remain truthful and the
   current project must revalidate before resuming.
4. Upload a small permissioned test clip. The UI must remain responsive and show
   real upload/progress/error states; it must not imply a completed analysis or
   timeline before the backend has actually completed it.
5. From Timeline Ready, open OpenReel. Confirm Preview and the compact native
   Timeline remain together, the playhead stays centered while the timeline
   moves beneath it, and Assets/Adjust sheets dismiss correctly.
6. Select a clip and exercise representative existing OpenReel tools such as
   split, trim, crop, speed, volume, and move. Background and reopen the app and
   confirm the latest whole-project snapshot restores.
7. If completing the export test, confirm both deliberate prompts: render/save
   first, then approve. Declining approval must not mark the project approved.

## Acceptance decision

After the walkthrough, explicitly choose one:

- **Approve and merge:** Phase 7 can be marked complete and `troy-facelift` may
  be merged into `main`.
- **Request changes:** keep the branch unmerged and record the exact screen,
  orientation, action, and observed behavior for another correction pass.
