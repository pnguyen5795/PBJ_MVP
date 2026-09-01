// Adapted for PBJ from OpenReel Video at pinned revision
// 5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9 (MIT).
import type { Project } from "@openreel/core";

export interface PBJProjection {
  schemaVersion: "pbj-openreel-project-v1";
  authority: {
    system: "pbj";
    projectId: string;
    revision: number;
    timelineHash: string;
    snapshotUrl: string;
    latestSnapshotUrl: string;
    exportIntentUrl: string;
    exportCompletionUrlTemplate: string;
    loadedFrom: "first_timeline" | "latest_snapshot";
    snapshotId?: string;
  };
  project: Project;
}

export const LAST_PBJ_PROJECT_KEY = "pbj.openreel.lastProjectId.v1";

export function pbjProjectIdFromLocation(location: Pick<Location, "search">): string | null {
  return new URLSearchParams(location.search).get("pbjProject");
}

export function isStandaloneDisplay(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(display-mode: standalone)").matches === true ||
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
}

export function pbjProjectIdForLaunch(
  location: Pick<Location, "search">,
  storage: Pick<Storage, "getItem">,
  standalone = isStandaloneDisplay(),
): string | null {
  const requested = pbjProjectIdFromLocation(location);
  if (requested) return requested;
  return standalone ? storage.getItem(LAST_PBJ_PROJECT_KEY) : null;
}

export function rememberPBJProject(
  projectId: string,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): void {
  storage.setItem(LAST_PBJ_PROJECT_KEY, projectId);
}

async function hydratePBJMedia(project: Project, signal?: AbortSignal): Promise<Project> {
  const items = [];
  for (const item of project.mediaLibrary.items) {
    if (item.blob || !item.originalUrl) {
      items.push(item);
      continue;
    }
    const response = await fetch(item.originalUrl, {
      credentials: "same-origin",
      signal,
    });
    if (!response.ok) {
      throw new Error(`PBJ media handoff failed for ${item.id} (${response.status})`);
    }
    const blob = await response.blob();
    items.push({
      ...item,
      blob,
      metadata: { ...item.metadata, fileSize: blob.size },
    });
  }
  return { ...project, mediaLibrary: { ...project.mediaLibrary, items } };
}

export async function fetchPBJProjection(
  projectId: string,
  signal?: AbortSignal,
): Promise<PBJProjection> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/openreel/project`,
    {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  if (!response.ok) throw new Error(`PBJ handoff failed (${response.status})`);
  const projection = (await response.json()) as PBJProjection;
  if (projection.schemaVersion !== "pbj-openreel-project-v1" || projection.authority.projectId !== projectId) {
    throw new Error("PBJ returned an incompatible OpenReel projection");
  }
  return { ...projection, project: await hydratePBJMedia(projection.project, signal) };
}
