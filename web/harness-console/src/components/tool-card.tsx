export function ToolCard({ name, args }: { name: string; args: unknown }) {
  return <div className="card"><strong>Tool · {name}</strong><pre>{JSON.stringify(args, null, 2)}</pre></div>;
}

