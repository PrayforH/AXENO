import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  groupTaskAgents,
  type TaskAgentGroup,
} from "../src/components/task-agent-switcher";
import type { TaskAgent } from "../src/lib/task-agent-catalog";

const component = readFileSync(
  join(process.cwd(), "src/components/task-agent-switcher.tsx"),
  "utf8",
);

const agents: TaskAgent[] = [
  {
    name: "research",
    version: "0.1.2",
    displayName: "联网研究",
    domain: "research",
  },
  {
    name: "writing",
    version: "0.1.0",
    displayName: "公文写作",
    domain: "writing",
  },
  {
    name: "research",
    version: "0.1.10",
    displayName: "联网研究",
    domain: "research",
  },
];

describe("task agent switcher", () => {
  it("groups many published versions under one agent and sorts versions newest first", () => {
    const groups: TaskAgentGroup[] = groupTaskAgents(agents);
    const research = groups.find((group) => group.name === "research");

    expect(groups).toHaveLength(2);
    expect(research?.agents.map((agent) => agent.version)).toEqual([
      "0.1.10",
      "0.1.2",
    ]);
  });

  it("searches display name, coordinate, version and domain", () => {
    expect(groupTaskAgents(agents, "公文")).toHaveLength(1);
    expect(groupTaskAgents(agents, "0.1.10")[0]?.name).toBe("research");
    expect(groupTaskAgents(agents, "research")[0]?.agents).toHaveLength(2);
    expect(groupTaskAgents(agents, "missing")).toEqual([]);
  });

  it("uses an accessible agent list and reserves a select for internal versions", () => {
    expect(component).toContain('aria-haspopup="listbox"');
    expect(component).toContain('role="listbox"');
    expect(component).toContain('role="option"');
    expect(component).toContain('type="search"');
    expect(component).toContain("切换后新建任务");
    expect(component).toContain("<select");
    expect(component).toContain("task-agent-version-select");
    expect(component).toContain("group.agents.length > 1");
    expect(component).toContain("`${selected.displayName} · ${selected.version}`");
  });
});
