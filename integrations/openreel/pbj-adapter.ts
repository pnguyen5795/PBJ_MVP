export interface PBJAuthority {
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
}

export interface PBJOpenReelProjection<ProjectShape = unknown> {
  schemaVersion: "pbj-openreel-project-v1";
  authority: PBJAuthority;
  project: ProjectShape;
}

export interface OpenReelProjectHost<ProjectShape> {
  loadProject(project: ProjectShape): void;
}

export async function fetchPBJProject<ProjectShape>(
  projectId: string,
  fetcher: typeof fetch = fetch,
): Promise<PBJOpenReelProjection<ProjectShape>> {
  const response = await fetcher(
    `/api/projects/${encodeURIComponent(projectId)}/openreel/project`,
    { credentials: "same-origin", headers: { Accept: "application/json" } },
  );
  if (!response.ok) {
    throw new Error(`PBJ project handoff failed (${response.status})`);
  }
  const projection = (await response.json()) as PBJOpenReelProjection<ProjectShape>;
  if (
    projection.schemaVersion !== "pbj-openreel-project-v1" ||
    projection.authority.system !== "pbj" ||
    projection.authority.projectId !== projectId
  ) {
    throw new Error("PBJ returned an incompatible OpenReel projection");
  }
  return projection;
}

export async function loadPBJProjectIntoOpenReel<ProjectShape>(
  projectId: string,
  host: OpenReelProjectHost<ProjectShape>,
  fetcher: typeof fetch = fetch,
): Promise<PBJOpenReelProjection<ProjectShape>> {
  const projection = await fetchPBJProject<ProjectShape>(projectId, fetcher);
  host.loadProject(projection.project);
  return projection;
}
