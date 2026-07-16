export function RunStatus({ status }: { status: string }) {
  return <span className="status"><span className="dot" />{status || "idle"}</span>;
}

