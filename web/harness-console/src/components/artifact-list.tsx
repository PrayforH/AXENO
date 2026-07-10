import type { Artifact } from "../lib/harness-client";
export function ArtifactList({ items, onDownload }: { items: Artifact[]; onDownload: (item: Artifact) => void }) {
  return <div className="stack">{items.map((item) => <button className="secondary" key={item.artifact_id} onClick={() => onDownload(item)}>{item.name} · {item.size_bytes ?? 0} bytes</button>)}</div>;
}
