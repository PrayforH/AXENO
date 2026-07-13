export interface ArtifactDetails {
  artifact_id: string;
  run_id: string;
  name?: string;
  media_type?: string;
  size_bytes?: number;
  sha256?: string;
}

export function formatBytes(value?: number) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}

export function ArtifactCard({ details }: { details: ArtifactDetails }) {
  return (
    <section className="domain-card artifact-domain-card">
      <div className="artifact-filemark" aria-hidden="true">
        TXT
      </div>
      <div className="artifact-copy">
        <div className="domain-card-kicker">运行产物</div>
        <h3>{details.name || "未命名产物"}</h3>
        <p>
          {details.media_type || "application/octet-stream"} · {formatBytes(details.size_bytes)}
        </p>
        {details.sha256 && <code>sha256 {details.sha256.slice(0, 12)}…</code>}
      </div>
      <a
        className="download-button"
        href={`/api/harness/artifacts/${encodeURIComponent(details.artifact_id)}`}
      >
        下载
      </a>
    </section>
  );
}
