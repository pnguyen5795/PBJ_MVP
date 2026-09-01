// Adapted for PBJ from OpenReel Video at pinned revision
// 5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9 (MIT).
export const MOBILE_EDITOR_MAX_WIDTH = 767;

export const PBJ_MOBILE_WORKSPACES = [
  ["stage", "Preview"],
  ["timeline", "Timeline"],
  ["media", "Media"],
  ["inspector", "Adjust"],
] as const;

export function isMobileEditorViewport(width: number): boolean {
  return width <= MOBILE_EDITOR_MAX_WIDTH;
}

export function shouldShowStandaloneMobileBlocker(
  width: number,
  pbjProjectId: string | null,
): boolean {
  return !pbjProjectId && isMobileEditorViewport(width);
}

export function keyboardMovedClipStart(
  currentStart: number,
  direction: "ArrowLeft" | "ArrowRight",
): number {
  const delta = direction === "ArrowLeft" ? -0.1 : 0.1;
  return Math.max(0, Number((currentStart + delta).toFixed(3)));
}
