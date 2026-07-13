"use client";

import { useState } from "react";
import { truncateLines } from "../lib/content-format";

interface CodeBlockProps {
  code: string;
  language?: string;
  maxLines?: number;
}

export function CodeBlock({ code, language = "text", maxLines = 500 }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const visible = truncateLines(code, maxLines);

  async function copy() {
    await navigator.clipboard?.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <section className="code-block" aria-label={`${language} 代码`}>
      <header className="code-block-header">
        <span>{language}</span>
        <button type="button" onClick={copy}>{copied ? "已复制" : "复制"}</button>
      </header>
      <pre>
        <code>
          {visible.value.split("\n").map((line, index) => (
            <span className="code-line" key={`${index}-${line}`}>
              <span className="code-line-number" aria-hidden="true">{index + 1}</span>
              <span className="code-line-content">{line || " "}</span>
            </span>
          ))}
        </code>
      </pre>
      {visible.truncated > 0 && (
        <p className="content-truncated">已隐藏 {visible.truncated} 行</p>
      )}
    </section>
  );
}
