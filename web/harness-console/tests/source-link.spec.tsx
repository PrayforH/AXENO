import { existsSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

async function sourceLink() {
  expect(existsSync("src/components/source-link.tsx")).toBe(true);
  return import("../src/components/source-link");
}

describe("source link", () => {
  it("shows the source host and opens external evidence safely", async () => {
    const { SourceLink } = await sourceLink();
    const html = renderToStaticMarkup(
      <SourceLink href="https://docs.example.com/reports/latest">
        Latest report
      </SourceLink>,
    );

    expect(html).toContain("Latest report");
    expect(html).toContain("docs.example.com");
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('class="source-link"');
  });

  it("keeps relative links inside the current application", async () => {
    const { SourceLink } = await sourceLink();
    const html = renderToStaticMarkup(
      <SourceLink href="/artifacts/report">Artifact</SourceLink>,
    );

    expect(html).toContain('href="/artifacts/report"');
    expect(html).not.toContain('target="_blank"');
    expect(html).not.toContain("source-host");
  });

  it("does not allow external source safety attributes to be weakened", async () => {
    const { SourceLink } = await sourceLink();
    const html = renderToStaticMarkup(
      <SourceLink
        href="https://docs.example.com/report"
        target="_self"
        rel="opener"
      >
        Report
      </SourceLink>,
    );

    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).not.toContain('target="_self"');
    expect(html).not.toContain('rel="opener"');
  });
});
