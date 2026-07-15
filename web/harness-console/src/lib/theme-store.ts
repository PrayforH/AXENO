"use client";

import { useCallback, useEffect, useState } from "react";

type Theme = "light" | "dark";

function getStoredTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return (window.localStorage.getItem("harness-theme") as Theme) ?? "light";
}

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
  window.localStorage.setItem("harness-theme", theme);
}

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function notify() {
  for (const listener of listeners) listener();
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === "light" ? "dark" : "light";
      applyTheme(next);
      notify();
      return next;
    });
  }, []);

  useEffect(() => {
    const unsub = subscribe(() => setThemeState(getStoredTheme()));
    return unsub;
  }, []);

  return { theme, toggleTheme };
}
