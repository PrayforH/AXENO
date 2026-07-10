export function AgentSelector(props: {
  name: string; version: string; onName: (value: string) => void; onVersion: (value: string) => void;
}) {
  return <div className="stack"><label className="label">Agent<input value={props.name} onChange={(e) => props.onName(e.target.value)} /></label><label className="label">Version<input value={props.version} onChange={(e) => props.onVersion(e.target.value)} /></label></div>;
}

