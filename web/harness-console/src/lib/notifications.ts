"use client";

import { useCallback, useEffect, useState } from "react";

let permission: NotificationPermission = "default";

async function requestPermission(): Promise<boolean> {
  if (!("Notification" in window)) return false;
  if (permission === "granted") return true;
  permission = await Notification.requestPermission();
  return permission === "granted";
}

function showNotification(title: string, body: string) {
  if (permission !== "granted") return;
  try {
    new Notification(title, { body, icon: "/favicon.ico" });
  } catch {
    // ignore
  }
}

export function useNotifications() {
  const [enabled, setEnabled] = useState(permission === "granted");

  const enable = useCallback(async () => {
    const ok = await requestPermission();
    setEnabled(ok);
  }, []);

  const disable = useCallback(() => {
    permission = "default";
    setEnabled(false);
  }, []);

  const notify = useCallback(
    (title: string, body: string) => {
      if (enabled) showNotification(title, body);
    },
    [enabled],
  );

  useEffect(() => {
    if (permission === "granted") setEnabled(true);
  }, []);

  return { enabled, enable, disable, notify };
}

export type NotificationHandler = ReturnType<typeof useNotifications>;
