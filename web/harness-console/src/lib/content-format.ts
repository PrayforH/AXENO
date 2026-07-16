export type ClassifiedContent =
  | { kind: "json"; value: unknown }
  | { kind: "code"; language: string; value: string }
  | { kind: "diff"; value: string }
  | { kind: "text"; value: string };

export interface SafeValueOptions {
  maxDepth?: number;
  maxItems?: number;
  maxKeys?: number;
}

export function toSafeValue(
  value: unknown,
  options: SafeValueOptions = {},
): unknown {
  const maxDepth = options.maxDepth ?? 8;
  const maxItems = options.maxItems ?? 100;
  const maxKeys = options.maxKeys ?? 100;
  const ancestors = new WeakSet<object>();

  function visit(current: unknown, depth: number): unknown {
    if (
      current === null ||
      typeof current === "string" ||
      typeof current === "boolean"
    ) {
      return current;
    }
    if (typeof current === "number") {
      return Number.isFinite(current) ? current : String(current);
    }
    if (typeof current === "bigint") return `${current.toString()}n`;
    if (typeof current === "undefined") return "[undefined]";
    if (typeof current === "function") return `[Function ${current.name || "anonymous"}]`;
    if (typeof current === "symbol") return current.toString();
    if (typeof current !== "object") return String(current);
    if (ancestors.has(current)) return "[Circular]";
    if (depth >= maxDepth) return "[Max depth reached]";

    ancestors.add(current);
    try {
      if (Array.isArray(current)) {
        const output = current.slice(0, maxItems).map((item) => visit(item, depth + 1));
        if (current.length > maxItems) {
          output.push(`[${current.length - maxItems} more items]`);
        }
        return output;
      }

      const entries = Object.entries(current);
      const output: Record<string, unknown> = {};
      for (const [key, item] of entries.slice(0, maxKeys)) {
        output[key] = visit(item, depth + 1);
      }
      if (entries.length > maxKeys) {
        output["…"] = `[${entries.length - maxKeys} more keys]`;
      }
      return output;
    } catch {
      return "[Unserializable value]";
    } finally {
      ancestors.delete(current);
    }
  }

  return visit(value, 0);
}

export function truncateLines(
  text: string,
  maxLines: number,
): { value: string; truncated: number } {
  const lines = text.split("\n");
  const safeMax = Math.max(1, maxLines);
  return {
    value: lines.slice(0, safeMax).join("\n"),
    truncated: Math.max(0, lines.length - safeMax),
  };
}

function looksLikeDiff(value: string): boolean {
  return (
    value.startsWith("diff --git ") ||
    (/^--- .+$/m.test(value) && /^\+\+\+ .+$/m.test(value)) ||
    (/^@@ .+ @@/m.test(value) && /^[-+][^-+]/m.test(value))
  );
}

export function classifyContent(value: unknown): ClassifiedContent {
  if (typeof value !== "string") {
    return { kind: "json", value: toSafeValue(value) };
  }

  const trimmed = value.trim();
  const fenced = trimmed.match(/^```([^\n`]*)\n([\s\S]*?)\n```$/);
  if (fenced) {
    return {
      kind: "code",
      language: fenced[1].trim() || "text",
      value: fenced[2],
    };
  }

  if (looksLikeDiff(trimmed)) return { kind: "diff", value: trimmed };

  if (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    try {
      return { kind: "json", value: toSafeValue(JSON.parse(trimmed)) };
    } catch {
      // It only looked like JSON. Preserve it as plain text.
    }
  }

  return { kind: "text", value };
}
