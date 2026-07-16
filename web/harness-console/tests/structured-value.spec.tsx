import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CodeBlock } from "../src/components/code-block";
import { DiffBlock } from "../src/components/diff-block";
import { StructuredValue } from "../src/components/structured-value";

describe("structured output components", () => {
  it("escapes values and renders JSON types", () => {
    const html = renderToStaticMarkup(
      <StructuredValue value={{ html: "<script>alert(1)</script>", ok: true }} />,
    );

    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("json-boolean");
  });

  it("renders code with language and line numbers", () => {
    const html = renderToStaticMarkup(
      <CodeBlock code={"const a = 1;\nreturn a;"} language="typescript" />,
    );

    expect(html).toContain("typescript");
    expect(html).toContain('class="code-line-number"');
    expect(html).toContain("复制");
  });

  it("styles unified diff additions and removals", () => {
    const html = renderToStaticMarkup(
      <DiffBlock diff={"@@ -1 +1 @@\n-old\n+new"} />,
    );

    expect(html).toContain("diff-line-remove");
    expect(html).toContain("diff-line-add");
  });
});
