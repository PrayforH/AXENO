"use client";

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "agent-harness-color-mode";

type ColorMode = "light" | "dark";

function isColorMode(value: string | null): value is ColorMode {
  return value === "light" || value === "dark";
}

function applyColorMode(mode: ColorMode) {
  const root = document.documentElement;
  root.dataset.colorMode = mode;
  root.style.colorScheme = mode;
  document
    .querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')
    .forEach((meta) => {
      meta.content = mode === "dark" ? "#181818" : "#f7f7f7";
    });
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [mode, setMode] = useState<ColorMode | null>(null);

  const syncColorMode = useCallback(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    const next = isColorMode(stored)
      ? stored
      : window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    applyColorMode(next);
    setMode(next);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    syncColorMode();
    window.addEventListener("storage", syncColorMode);
    media.addEventListener("change", syncColorMode);
    return () => {
      window.removeEventListener("storage", syncColorMode);
      media.removeEventListener("change", syncColorMode);
    };
  }, [syncColorMode]);

  function toggleColorMode() {
    const current =
      mode ??
      (document.documentElement.dataset.colorMode === "light"
        ? "light"
        : "dark");
    const next = current === "dark" ? "light" : "dark";
    window.localStorage.setItem(STORAGE_KEY, next);
    applyColorMode(next);
    setMode(next);
  }

  const nextLabel = mode === "light" ? "深色" : "浅色";

  return (
    <button
      className={`theme-toggle ${className}`.trim()}
      type="button"
      data-mode={mode ?? undefined}
      aria-label={`切换到${nextLabel}主题`}
      title={`切换到${nextLabel}主题`}
      onClick={toggleColorMode}
    >
      <span className="theme-toggle-track" aria-hidden="true">
        <svg className="theme-toggle-sun" viewBox="0 0 20 20">
          <circle cx="10" cy="10" r="3.2" />
          <path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M4 4l1.4 1.4M14.6 14.6 16 16M16 4l-1.4 1.4M5.4 14.6 4 16" />
        </svg>
        <svg className="theme-toggle-moon" viewBox="0 0 20 20">
          <path d="M16.3 12.6A6.7 6.7 0 0 1 7.4 3.7a6.7 6.7 0 1 0 8.9 8.9Z" />
        </svg>
      </span>
      <span className="theme-toggle-label" aria-hidden="true">
        {mode === "light" ? "浅色" : mode === "dark" ? "深色" : "主题"}
      </span>
    </button>
  );
}
