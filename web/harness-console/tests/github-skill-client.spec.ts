import { describe, expect, it, vi } from "vitest";
import {
  createStoredZip,
  downloadOnlineSkillInBrowser,
} from "../src/lib/github-skill-client";

describe("GitHub Skill browser fallback", () => {
  it("downloads a direct GitHub SKILL.md", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      expect(String(input)).toBe(
        "https://raw.githubusercontent.com/acme/skills/main/office/SKILL.md",
      );
      return new Response("---\nname: office\ndescription: Office\n---\nBuild it.\n");
    });

    const file = await downloadOnlineSkillInBrowser(
      "https://github.com/acme/skills/blob/main/office/SKILL.md",
    );

    expect(file.name).toBe("SKILL.md");
    expect(await file.text()).toContain("name: office");
  });

  it("downloads a GitHub directory and preserves its files in a ZIP", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/contents/skills/office?")) {
        return Response.json([
          {
            download_url: "https://raw.githubusercontent.com/acme/skills/main/skills/office/SKILL.md",
            name: "SKILL.md",
            path: "skills/office/SKILL.md",
            size: 60,
            type: "file",
          },
          {
            download_url: null,
            name: "scripts",
            path: "skills/office/scripts",
            size: 0,
            type: "dir",
          },
        ]);
      }
      if (url.includes("/contents/skills/office/scripts?")) {
        return Response.json([
          {
            download_url: "https://raw.githubusercontent.com/acme/skills/main/skills/office/scripts/build.py",
            name: "build.py",
            path: "skills/office/scripts/build.py",
            size: 12,
            type: "file",
          },
        ]);
      }
      if (url.endsWith("/SKILL.md")) {
        return new Response("---\nname: office\ndescription: Office\n---\nBuild it.\n");
      }
      if (url.endsWith("/build.py")) return new Response("print('ok')\n");
      return new Response("not found", { status: 404 });
    });

    const file = await downloadOnlineSkillInBrowser(
      "https://github.com/acme/skills/tree/main/skills/office",
    );
    const content = new Uint8Array(await file.arrayBuffer());
    const visible = new TextDecoder().decode(content);

    expect(file.name).toBe("office.zip");
    expect(new DataView(content.buffer).getUint32(0, true)).toBe(0x04034b50);
    expect(visible).toContain("SKILL.md");
    expect(visible).toContain("scripts/build.py");
    expect(visible).not.toContain("skills/office/SKILL.md");
  });

  it("writes a valid empty-free stored ZIP directory", () => {
    const archive = createStoredZip([
      { path: "SKILL.md", content: new TextEncoder().encode("skill") },
    ]);
    const view = new DataView(archive.buffer);
    expect(view.getUint32(0, true)).toBe(0x04034b50);
    expect(view.getUint32(archive.byteLength - 22, true)).toBe(0x06054b50);
  });
});
