# OpenReel integration patch

Apply these changes to pinned OpenReel `apps/web/src/App.tsx`:

1. Import the PBJ project loader and whole-project snapshot bridge.
2. On mount, read `pbjProject`, fetch PBJ's projection, hydrate every permitted `originalUrl` into the browser `Blob` required by OpenReel playback/rendering, and load it through OpenReel's existing `loadProject` store method. Fail the handoff visibly if admitted media cannot be loaded; never render empty frames.
3. Skip the welcome screen and navigate to OpenReel's existing editor route.
4. Subscribe once to OpenReel's project store and debounce complete project snapshot saves to PBJ.
5. Remove browser-only blobs, file handles, waveform buffers, and `blob:` URLs from the serialized snapshot.
6. Dispose of the subscription when the app unmounts.
7. In `apps/web/vite.config.ts`, proxy `/api` to `PBJ_API_ORIGIN` (default
   `http://127.0.0.1:8000`) so the OpenReel host keeps PBJ API calls and the
   device session behind the same browser origin.
8. Suppress OpenReel's local recovery dialog when `pbjProject` is present.
   PBJ's validated latest snapshot is the single recovery source for a PBJ
   editing session; standalone OpenReel projects retain native recovery.
9. Store the active PBJ projection in `pbj-export.ts` while the PBJ session is
   mounted and clear it on unmount.
10. In `Toolbar.tsx`, label the PBJ primary action **Export & Approve** and use
    only OpenReel's existing standard H.264 MP4 export path. Before rendering,
    save the whole project and create a PBJ export intent. Mirror the renderer's
    writable stream into a temporary OPFS file, hash that file incrementally,
    submit the metadata-only render receipt, and delete the temporary mirror.
11. Show accessible in-editor confirmation panels, portaled to `document.body`, before export and again after
    the verified MP4 is saved. Do not use blocking browser-native dialogs. Only
    the second confirmation calls PBJ's approval endpoint.
    A declined second confirmation leaves the render truthfully pending approval.
12. PBJ sessions hide alternate export choices until their formats have matching
    receipt contracts. Standalone OpenReel sessions retain the native export UI.
13. PBJ browser sessions use the direct OPFS-backed download writable instead of
    a desktop save-file picker, keeping Export & Approve usable in an installed
    iPhone PWA. Standalone OpenReel sessions retain their native save behavior.
14. In `CropModeView.tsx`, calculate preset crop ratios in source pixel space,
    not normalized percentage space. This fixes square and portrait presets on
    non-square media while leaving OpenReel's crop tool and project contract intact.
15. In `ClipComponent.tsx`, expose OpenReel's existing move operation through
    Option/Alt + Left/Right in 0.1-second steps. Pointer dragging remains native;
    the keyboard path improves accessibility and does not create a PBJ command.
16. In `EditorInterface.tsx`, replace the fixed multi-column grid below 768px
    with a safe-area-aware Preview, Timeline, Media, and Adjust workspace
    switcher. Each destination renders OpenReel's existing panel and project
    state; PBJ does not create a second mobile editor.
17. In `Toolbar.tsx`, collapse desktop-only mode and project-switcher controls
    below 768px while keeping the project name and explicit Export & Approve
    action visible in a compact top bar.
18. In `ClipComponent.tsx`, use OpenReel pointer events for its existing clip
    move and trim interactions so the same implementation accepts mouse, pen,
    and touch input. On narrow screens, enlarge the invisible trim hit areas
    without changing the stored project operation or desktop presentation.
19. In `MobileBlocker.tsx`, never cover a PBJ project with OpenReel's inherited
    standalone Desktop Only overlay. Standalone behavior uses viewport width,
    not user-agent sniffing. In `index.html`, opt into iPhone safe-area layout
    and standalone web-app presentation; use dynamic viewport height in
    `App.tsx`, and allow both orientations in `public/manifest.json`.
20. In `pbj-sync.ts`, flush a dirty whole-project snapshot immediately when
    Safari reports `visibilitychange` to hidden or `pagehide`. Prefer a
    keepalive request only below the conservative 60 KB browser limit; larger
    projects use the normal request path instead of risking keepalive rejection.
21. In `pbj-project-loader.ts`, remember only the last successfully loaded PBJ
    project ID in device-local storage. A Home Screen standalone launch may use
    that pointer, but must refetch the projection so PBJ revalidates the session,
    permission, snapshot, and media. `App.tsx` shows an explicit recovery state
    if that validation fails; ordinary browser launches never infer a project.
22. Hydrate PBJ's already-prepared mobile-safe per-source proxies sequentially,
    not concurrently, and record each hydrated proxy's actual byte size in the
    OpenReel media metadata. Pass one abort signal through projection and media
    requests so closing or replacing the page cancels abandoned downloads.
23. Keep the mobile workspace navigation outside the one-panel editor grid so
    it remains visible below Preview, Timeline, Media, and Adjust. In `App.tsx`,
    apply `100dvh` as an inline progressive enhancement over the `100vh`
    fallback so Safari cannot cascade the desktop height back over the dynamic
    viewport and push player controls/navigation under its bottom chrome.
24. Replace the first one-panel mobile workspace scaffold with an iPhone-first
    editing shell inspired by familiar short-form editors: keep OpenReel's
    Preview and a compact native Timeline visible together, place its existing
    clip actions in a contextual bottom tray, and present the existing Assets
    and Inspector panels as dismissible bottom sheets. `Timeline.tsx` may hide
    its desktop-only toolbar and track-header column in compact mode, but it
    must keep the same tracks, clips, selection, playhead, project store, and
    editing operations. On mobile, pin the playhead at the horizontal center
    and scroll the padded native timeline beneath it; scrolling scrubs the
    existing OpenReel playhead time, and playback advances the timeline under
    the fixed line. **Export & Approve** remains pinned in the toolbar.

Do not add callbacks to individual editor tools. OpenReel owns move, trim, split,
crop, playback, undo/redo, and all other editing behavior. PBJ receives complete
project snapshots, not a separate transaction for each tool action.

The working evaluation checkout contains this exact patch for verification. The
overlay is retained in PBJ so the integration is reproducible without committing
the isolated `.evaluations/` checkout.
