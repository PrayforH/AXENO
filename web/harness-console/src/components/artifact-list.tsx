import type { Artifact } from "../lib/harness-client";
export function ArtifactList({ items, url }: { items: Artifact[]; url: (id: string) => string }) {
  return <div className="stack">{items.map((item) => <a key={item.artifact_id} href={url(item.artifact_id)}>{item.name} · {item.size_bytes ?? 0} bytes</a>)}</div>;
}

