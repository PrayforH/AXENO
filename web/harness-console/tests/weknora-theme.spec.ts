import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const layout = readFileSync(join(process.cwd(), "src/app/layout.tsx"), "utf8");
const theme = readFileSync(
  join(process.cwd(), "src/app/weknora-theme.css"),
  "utf8",
);
const themeSelector = readFileSync(
  join(process.cwd(), "src/components/theme-toggle.tsx"),
  "utf8",
);
const taskSidebar = readFileSync(
  join(process.cwd(), "src/components/task-sidebar.tsx"),
  "utf8",
);
const studioSidebar = readFileSync(
  join(process.cwd(), "src/components/agent-studio/studio-sidebar.tsx"),
  "utf8",
);
const studioStyles = readFileSync(
  join(
    process.cwd(),
    "src/components/agent-studio/agent-studio.module.css",
  ),
  "utf8",
);
const workspaceNavigationStyles = readFileSync(
  join(process.cwd(), "src/components/workspace-navigation.module.css"),
  "utf8",
);

describe("Weknora-inspired product theme", () => {
  it("loads the product layer after the legacy theme and identifies the UI generation", () => {
    expect(layout.indexOf('import "./weknora-theme.css"')).toBeGreaterThan(
      layout.indexOf('import "./codex-theme.css"'),
    );
    expect(layout).toContain('data-product-ui="weknora"');
    expect(layout).toContain('color: "#fbfcfb"');
  });

  it("uses a warm light canvas with one green product accent", () => {
    expect(theme).toMatch(
      /html\[data-color-mode="light"\]\s*\{[^}]*--codex-surface:\s*#fbfcfb;[^}]*--codex-accent:\s*#16b364;/s,
    );
    expect(theme).toMatch(
      /html\[data-color-mode="light"\] body::before\s*\{[^}]*display:\s*none;/s,
    );
    expect(themeSelector).toContain("温和白底与绿色强调");
  });

  it("flattens and enlarges high-frequency sidebar navigation", () => {
    expect(workspaceNavigationStyles).toMatch(
      /\.navigationLink,\s*\.navigationActive\s*\{[^}]*min-height:\s*40px;[^}]*font-size:\s*12\.5px;/s,
    );
    expect(workspaceNavigationStyles).toMatch(
      /data-color-mode="light"[^}]*\.navigationActive\s*\{[^}]*box-shadow:\s*none;/s,
    );
    expect(taskSidebar).not.toContain("智能任务工作台");
    expect(studioSidebar).not.toContain("智能体控制面");
    expect(theme).toMatch(
      /\.task-sidebar-primary button\s*\{[^}]*min-height:\s*42px;[^}]*color:\s*var\(--codex-accent\);/s,
    );
  });

  it("keeps settings and Studio on the same quiet surface hierarchy", () => {
    expect(theme).toMatch(
      /\.settings-layout\s*\{[^}]*grid-template-columns:\s*180px minmax\(0, 780px\);/s,
    );
    expect(theme).toMatch(
      /\.settings-form\s*\{[^}]*border-radius:\s*12px;[^}]*background:\s*#ffffff;/s,
    );
    expect(studioStyles).toMatch(
      /data-color-mode="light"[^}]*\.workspaceTabActive,[\s\S]*?box-shadow:\s*none;/,
    );
    expect(studioStyles).toContain("--studio-green: var(--codex-accent)");
  });
});
