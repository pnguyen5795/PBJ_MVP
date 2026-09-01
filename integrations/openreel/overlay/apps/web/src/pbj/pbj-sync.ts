// PBJ integration overlay for OpenReel Video revision
// 5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9 (MIT).
import type { Project } from "@openreel/core";
import type { PBJProjection } from "./pbj-project-loader";

type ProjectState = { project: Project };
type ProjectStore = {
  getState(): ProjectState;
  subscribe(listener: (state: ProjectState, previous: ProjectState) => void): () => void;
};

export function snapshotProject(project: Project): Project {
  return JSON.parse(JSON.stringify(project, (key, value) => {
    if (["blob", "fileHandle", "waveformData"].includes(key)) return null;
    if (typeof value === "string" && value.startsWith("blob:")) return null;
    return value;
  })) as Project;
}

export async function savePBJSnapshot(
  projection: PBJProjection,
  project: Project,
  fetcher: typeof fetch = fetch,
  preferKeepalive = false,
): Promise<{ snapshot_id: string }> {
  const body = JSON.stringify({
    schema_version: "pbj-openreel-snapshot-v1",
    source_timeline_revision: projection.authority.revision,
    source_timeline_hash: projection.authority.timelineHash,
    project: snapshotProject(project),
  });
  const keepalive = preferKeepalive && new TextEncoder().encode(body).byteLength <= 60_000;
  const response = await fetcher(projection.authority.snapshotUrl, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body,
    keepalive,
  });
  if (!response.ok) throw new Error(`PBJ snapshot save failed (${response.status})`);
  return response.json() as Promise<{ snapshot_id: string }>;
}

export function installPBJSnapshotSync(
  projection: PBJProjection,
  store: ProjectStore,
  debounceMs = 750,
  fetcher: typeof fetch = fetch,
): () => void {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let dirty = false;

  const flush = (preferKeepalive = false) => {
    if (!dirty) return;
    dirty = false;
    if (timeout) clearTimeout(timeout);
    timeout = undefined;
    void savePBJSnapshot(
      projection,
      store.getState().project,
      fetcher,
      preferKeepalive,
    ).catch((error) => {
      dirty = true;
      console.error("PBJ could not save the OpenReel project snapshot", error);
    });
  };

  const unsubscribe = store.subscribe((state, previous) => {
    if (state.project === previous.project) return;
    dirty = true;
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(() => flush(), debounceMs);
  });

  const handleVisibilityChange = () => {
    if (document.visibilityState === "hidden") flush(true);
  };
  const handlePageHide = () => flush(true);
  document.addEventListener("visibilitychange", handleVisibilityChange);
  window.addEventListener("pagehide", handlePageHide);

  return () => {
    if (timeout) clearTimeout(timeout);
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    window.removeEventListener("pagehide", handlePageHide);
    unsubscribe();
  };
}
