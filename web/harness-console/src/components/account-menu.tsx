"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "./auth-provider";

const ROLE_LABELS = {
  owner: "所有者",
  admin: "管理员",
  member: "成员",
  viewer: "只读",
} as const;

export function AccountMenu() {
  const { user, membership } = useAuth();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const initial = (user.display_name || user.email).trim().slice(0, 1).toUpperCase();

  useEffect(() => {
    if (!open) return;
    function closeOnOutsideClick(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className="account-menu" ref={menuRef}>
      <button
        className="account-trigger"
        type="button"
        aria-expanded={open}
        aria-label="账户菜单"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="account-trigger-avatar" aria-hidden="true">{initial}</span>
        <span className="account-trigger-copy">
          <strong>{user.display_name}</strong>
          <small>{ROLE_LABELS[membership.role]}</small>
        </span>
      </button>
      {open && (
        <div className="account-popover" role="dialog" aria-label="当前账户">
          <div className="account-identity">
            <strong>{user.display_name}</strong>
            <span>{user.email}</span>
          </div>
          <div className="account-role">
            <span>{ROLE_LABELS[membership.role]}</span>
            <code>{membership.tenant_id}</code>
          </div>
          <nav className="account-actions" aria-label="账户操作">
            <a className="account-settings" href="/settings">个人设置</a>
            <a className="account-logout" href="/api/auth/logout">退出登录</a>
          </nav>
        </div>
      )}
    </div>
  );
}
