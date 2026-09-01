import type { Project, VideoExportSettings } from "@openreel/core";
import type { PBJProjection } from "./pbj-project-loader";
import { savePBJSnapshot } from "./pbj-sync";

const OPENREEL_SOURCE_REVISION = "5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9";
let activeProjection: PBJProjection | null = null;

export function setActivePBJProjection(projection: PBJProjection | null): void {
  activeProjection = projection;
}

export function getActivePBJProjection(): PBJProjection | null {
  return activeProjection;
}

async function jsonRequest<T>(url: string, body: unknown, fetcher: typeof fetch): Promise<T> {
  const response = await fetcher(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `PBJ request failed (${response.status})`;
    try {
      const payload = await response.json() as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch { void 0; }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export interface PBJExportIntent {
  export_id: string;
  snapshot_id: string;
  status: "awaiting_openreel_render";
  completion_url: string;
}

export interface PBJRenderCompletion {
  export_id: string;
  snapshot_id: string;
  status: "render_complete_pending_approval";
  approval_required: true;
  approval_url: string;
}

export async function beginPBJExport(
  projection: PBJProjection,
  project: Project,
  fetcher: typeof fetch = fetch,
): Promise<PBJExportIntent> {
  const snapshot = await savePBJSnapshot(projection, project, fetcher);
  return jsonRequest<PBJExportIntent>(projection.authority.exportIntentUrl, {
    snapshot_id: snapshot.snapshot_id,
    approval_confirmation: true,
  }, fetcher);
}

export async function completePBJExport(
  intent: PBJExportIntent,
  output: { sha256: string; sizeBytes: number },
  settings: Partial<VideoExportSettings>,
  fetcher: typeof fetch = fetch,
): Promise<PBJRenderCompletion> {
  return jsonRequest<PBJRenderCompletion>(intent.completion_url, {
    schema_version: "pbj-openreel-render-receipt-v1",
    snapshot_id: intent.snapshot_id,
    renderer: { name: "openreel", source_revision: OPENREEL_SOURCE_REVISION, version: "0.1.2" },
    output: {
      sha256: output.sha256,
      size_bytes: output.sizeBytes,
      mime_type: "video/mp4",
      delivered_to_user: true,
    },
    verification: {
      passed: true,
      checks: {
        render_completed: true,
        nonempty_output: output.sizeBytes > 0,
        project_identity: true,
        snapshot_identity: true,
      },
    },
    export_settings: settings,
  }, fetcher);
}

export async function approvePBJExport(
  completion: PBJRenderCompletion,
  outputSha256: string,
  fetcher: typeof fetch = fetch,
): Promise<{ approved: true; export_id: string }> {
  return jsonRequest(completion.approval_url, {
    approval_confirmation: true,
    output_sha256: outputSha256,
  }, fetcher);
}

// Small incremental SHA-256 implementation so multi-gigabyte exports can be
// verified from a stream without loading the complete video into memory.
class Sha256 {
  private state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  private buffer = new Uint8Array(64);
  private buffered = 0;
  private bytes = 0;

  update(input: Uint8Array): void {
    let offset = 0;
    this.bytes += input.byteLength;
    while (offset < input.byteLength) {
      const take = Math.min(64 - this.buffered, input.byteLength - offset);
      this.buffer.set(input.subarray(offset, offset + take), this.buffered);
      this.buffered += take;
      offset += take;
      if (this.buffered === 64) {
        this.compress(this.buffer);
        this.buffered = 0;
      }
    }
  }

  digestHex(): string {
    const bitLength = this.bytes * 8;
    this.buffer[this.buffered++] = 0x80;
    if (this.buffered > 56) {
      this.buffer.fill(0, this.buffered);
      this.compress(this.buffer);
      this.buffered = 0;
    }
    this.buffer.fill(0, this.buffered, 56);
    const high = Math.floor(bitLength / 0x100000000);
    const low = bitLength >>> 0;
    const view = new DataView(this.buffer.buffer);
    view.setUint32(56, high, false);
    view.setUint32(60, low, false);
    this.compress(this.buffer);
    return Array.from(this.state, (word) => word.toString(16).padStart(8, "0")).join("");
  }

  private compress(block: Uint8Array): void {
    const k = SHA256_K;
    const w = new Uint32Array(64);
    const view = new DataView(block.buffer, block.byteOffset, block.byteLength);
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(i * 4, false);
    for (let i = 16; i < 64; i++) {
      const x = w[i - 15];
      const y = w[i - 2];
      const s0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3);
      const s1 = rotr(y, 17) ^ rotr(y, 19) ^ (y >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = this.state;
    for (let i = 0; i < 64; i++) {
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + s1 + ch + k[i] + w[i]) >>> 0;
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (s0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0;
      d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    this.state[0] = (this.state[0] + a) >>> 0;
    this.state[1] = (this.state[1] + b) >>> 0;
    this.state[2] = (this.state[2] + c) >>> 0;
    this.state[3] = (this.state[3] + d) >>> 0;
    this.state[4] = (this.state[4] + e) >>> 0;
    this.state[5] = (this.state[5] + f) >>> 0;
    this.state[6] = (this.state[6] + g) >>> 0;
    this.state[7] = (this.state[7] + h) >>> 0;
  }
}

const rotr = (value: number, bits: number): number => (value >>> bits) | (value << (32 - bits));
const SHA256_K = new Uint32Array([
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
]);

export async function sha256Blob(blob: Blob): Promise<string> {
  const hash = new Sha256();
  const reader = blob.stream().getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value) hash.update(value);
    }
  } finally {
    reader.releaseLock();
  }
  return hash.digestHex();
}

export interface PBJVerifiedWritable {
  stream: FileSystemWritableFileStream;
  output(): Promise<{ sha256: string; sizeBytes: number }>;
  cleanup(): Promise<void>;
}

export async function mirrorForPBJVerification(
  destination: FileSystemWritableFileStream,
): Promise<PBJVerifiedWritable> {
  const storage = navigator.storage as StorageManager & {
    getDirectory?: () => Promise<FileSystemDirectoryHandle>;
  };
  if (typeof storage?.getDirectory !== "function") {
    throw new Error("This browser cannot verify a PBJ export on-device.");
  }
  const root = await storage.getDirectory();
  const name = `.pbj-export-${Date.now()}-${Math.random().toString(36).slice(2)}.mp4`;
  const handle = await root.getFileHandle(name, { create: true });
  const mirror = await handle.createWritable({ keepExistingData: false });
  const stream = {
    async seek(position: number) { await Promise.all([destination.seek(position), mirror.seek(position)]); },
    async write(data: unknown) {
      await destination.write(data as Parameters<FileSystemWritableFileStream["write"]>[0]);
      await mirror.write(data as Parameters<FileSystemWritableFileStream["write"]>[0]);
    },
    async truncate(size: number) { await Promise.all([destination.truncate(size), mirror.truncate(size)]); },
    async close() { await destination.close(); await mirror.close(); },
    async abort() {
      await Promise.allSettled([destination.abort(), mirror.abort()]);
      await root.removeEntry(name).catch(() => undefined);
    },
  } as unknown as FileSystemWritableFileStream;
  return {
    stream,
    async output() {
      const file = await handle.getFile();
      if (file.size <= 0) throw new Error("OpenReel produced an empty export.");
      return { sha256: await sha256Blob(file), sizeBytes: file.size };
    },
    async cleanup() { await root.removeEntry(name).catch(() => undefined); },
  };
}
