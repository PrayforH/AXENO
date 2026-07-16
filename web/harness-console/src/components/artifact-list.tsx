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
  const contentUrl = `/api/harness/artifacts/${encodeURIComponent(details.artifact_id)}`;
  const mediaType = details.media_type || "application/octet-stream";
  const previewable =
    mediaType.startsWith("text/") ||
    mediaType.startsWith("image/") ||
    mediaType === "application/json" ||
    mediaType === "application/pdf";
  const filemark = mediaType.includes("json")
    ? "JSON"
    : mediaType.includes("pdf")
      ? "PDF"
      : mediaType.startsWith("image/")
        ? "IMG"
        : "FILE";
  return (
    <section className="domain-card artifact-domain-card">
      <div className="artifact-filemark" aria-hidden="true">
        {filemark}
      </div>
      <div className="artifact-copy">
        <div className="domain-card-kicker">运行产物</div>
        <h3>{details.name || "未命名产物"}</h3>
        <p>
          {mediaType} · {formatBytes(details.size_bytes)}
        </p>
        {details.sha256 && <code>sha256 {details.sha256.slice(0, 12)}…</code>}
      </div>
      <div className="artifact-actions">
        {previewable && (
          <a
            className="preview-button"
            href={`${contentUrl}?preview=1`}
            target="_blank"
            rel="noreferrer"
          >
            <span>预览</span><i aria-hidden="true">↗</i>
          </a>
        )}
        <a className="download-button" href={contentUrl}>
          <span>下载</span><i aria-hidden="true">↓</i>
        </a>
      </div>
    </section>
  );
}
