"use client";

import { useEffect } from "react";

const copySelector = '[data-streamdown="code-block-copy-button"]';
const downloadSelector = '[data-streamdown="code-block-download-button"]';

type ObserverHandle = {
  disconnect: () => void;
  observe: (target: Node, options: MutationObserverInit) => void;
};

type EnhancerOptions = {
  createObserver?: (callback: () => void) => ObserverHandle;
  schedule?: (callback: () => void) => number;
  cancel?: (timer: number) => void;
};

function setCopyState(button: HTMLElement, copied: boolean) {
  if (copied) button.setAttribute("data-copy-state", "copied");
  else button.removeAttribute("data-copy-state");
  const label = copied ? "已复制" : "复制代码";
  button.setAttribute("aria-label", label);
  button.setAttribute("title", label);
}

export function normalizeMarkdownControls(root: Document) {
  root.querySelectorAll<HTMLElement>(downloadSelector).forEach((button) => {
    button.hidden = true;
    button.setAttribute("aria-hidden", "true");
  });
  root.querySelectorAll<HTMLElement>(copySelector).forEach((button) => {
    setCopyState(button, button.getAttribute("data-copy-state") === "copied");
  });
}

export function installMarkdownControlEnhancer(
  root: Document,
  options: EnhancerOptions = {},
) {
  const createObserver =
    options.createObserver ?? ((callback) => new MutationObserver(callback));
  const schedule =
    options.schedule ?? ((callback) => window.setTimeout(callback, 1400));
  const cancel = options.cancel ?? ((timer) => window.clearTimeout(timer));
  const timers = new Map<HTMLElement, number>();

  normalizeMarkdownControls(root);
  const observer = createObserver(() => normalizeMarkdownControls(root));
  observer.observe(root.body, { childList: true, subtree: true });

  function onClick(event: Event) {
    const target = event.target as { closest?: (selector: string) => HTMLElement | null } | null;
    const button = target?.closest?.(copySelector);
    if (!button) return;
    const previousTimer = timers.get(button);
    if (previousTimer !== undefined) cancel(previousTimer);
    setCopyState(button, true);
    const timer = schedule(() => {
      timers.delete(button);
      setCopyState(button, false);
    });
    timers.set(button, timer);
  }

  root.addEventListener("click", onClick);
  return () => {
    observer.disconnect();
    root.removeEventListener("click", onClick);
    timers.forEach(cancel);
    timers.clear();
  };
}

export function MarkdownControlObserver() {
  useEffect(() => installMarkdownControlEnhancer(document), []);
  return null;
}
