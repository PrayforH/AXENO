"use client";

import {
  MarkdownTextPrimitive,
  type CodeHeaderProps,
} from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";
import { memo, useState } from "react";
import { SourceLink } from "./source-link";

function CodeHeader({ language, code }: CodeHeaderProps) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard?.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="aui-code-header">
      <span>{language || "text"}</span>
      <button type="button" onClick={copy} aria-label="复制代码">
        {copied ? "已复制" : "复制"}
      </button>
    </div>
  );
}

function MarkdownTextImpl() {
  return (
    <MarkdownTextPrimitive
      className="aui-md"
      remarkPlugins={[remarkGfm]}
      components={{ CodeHeader, a: SourceLink }}
      defer
    />
  );
}

export const MarkdownText = memo(MarkdownTextImpl);
