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
  const primaryUrl = previewable ? `${contentUrl}?preview=1` : contentUrl;
  const filemark = mediaType.includes("json")
    ? "JSON"
    : mediaType.includes("pdf")
      ? "PDF"
      : mediaType.startsWith("image/")
        ? "IMG"
        : "FILE";
  return (
    <section className="domain-card artifact-domain-card">
      <a
        className="artifact-primary-link"
        href={primaryUrl}
        target={previewable ? "_blank" : undefined}
        rel={previewable ? "noreferrer" : undefined}
        download={previewable ? undefined : details.name}
        aria-label={previewable ? `预览 ${details.name || "运行产物"}` : `下载 ${details.name || "运行产物"}`}
        title={previewable ? `点击预览 ${details.name || "运行产物"}` : `点击下载 ${details.name || "运行产物"}`}
      >
        <div className="artifact-filemark" aria-hidden="true">
          {filemark}
        </div>
        <div className="artifact-copy">
          <h3>
            {details.name || "未命名产物"}
            <span aria-hidden="true">{previewable ? "↗" : "↓"}</span>
          </h3>
          <p>
            <span>运行产物</span> · {mediaType} · {formatBytes(details.size_bytes)}
            {details.sha256 && <code title={`sha256 ${details.sha256}`}> · {details.sha256.slice(0, 8)}</code>}
          </p>
        </div>
      </a>
    </section>
  );
}
