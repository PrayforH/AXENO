export const PRODUCT_NAME = "序枢";
export const PRODUCT_DESCRIPTOR = "AGENT OPERATIONS";
export const PRODUCT_DESCRIPTION = "面向组织的智能体任务、能力与运行治理平台";

export function ProductBrandMark({
  className = "",
}: {
  className?: string;
}) {
  return (
    <span
      className={`product-brand-mark ${className}`.trim()}
      aria-hidden="true"
    >
      <svg viewBox="0 0 32 32" focusable="false">
        <path
          className="product-brand-track"
          d="M8 8h11.5c3 0 4.5 1.35 4.5 3.45s-1.5 3.55-4.5 3.55h-7C9.5 15 8 16.45 8 18.55S9.5 22 12.5 22H24"
        />
        <rect className="product-brand-origin" x="5.5" y="5.5" width="5" height="5" rx="1.25" />
        <path className="product-brand-core" d="m16 12.5 3.5 3.5-3.5 3.5-3.5-3.5Z" />
        <path className="product-brand-terminal" d="M21.5 19.5h5v5h-5z" />
      </svg>
    </span>
  );
}

export function ProductBrandCopy({
  compact = false,
  className = "",
}: {
  compact?: boolean;
  className?: string;
}) {
  return (
    <span className={`product-brand-copy ${className}`.trim()}>
      <strong>{PRODUCT_NAME}</strong>
      {!compact && <small>{PRODUCT_DESCRIPTOR}</small>}
    </span>
  );
}
