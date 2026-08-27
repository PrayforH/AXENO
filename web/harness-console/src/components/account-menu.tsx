"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "./auth-provider";
import { ProductIcon } from "./product-icon";
import { WorkspaceIcon, type WorkspaceId } from "./workspace-navigation";

const ROLE_LABELS = {
  owner: "所有者",
  admin: "管理员",
  member: "成员",
  viewer: "只读",
} as const;

const RESOURCE_WORKSPACES: ReadonlyArray<{
  id: WorkspaceId;
  href: string;
  label: string;
}> = [
  { id: "capabilities", href: "/studio/capabilities", label: "MCP 能力" },
  { id: "knowledge", href: "/studio/knowledge", label: "知识库" },
  { id: "spaces", href: "/studio/spaces", label: "协作空间" },
];

export function AccountMenu() {
  const { user, membership } = useAuth();
  const pathname = usePathname();
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
        <svg className="account-trigger-chevron" viewBox="0 0 16 16" aria-hidden="true">
          <path d={open ? "m4 10 4-4 4 4" : "m4 6 4 4 4-4"} />
        </svg>
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
          <nav className="account-workspaces" aria-label="资源与协作">
            <span className="account-section-label">资源与协作</span>
            {RESOURCE_WORKSPACES.map((workspace) => {
              const current = pathname.startsWith(workspace.href);
              return (
                <Link
                  className="account-workspace-link"
                  href={workspace.href}
                  aria-current={current ? "page" : undefined}
                  onClick={() => setOpen(false)}
                  key={workspace.id}
                >
                  <WorkspaceIcon workspace={workspace.id} />
                  <span>{workspace.label}</span>
                  <svg className="account-link-arrow" viewBox="0 0 16 16" aria-hidden="true">
                    <path d="m6 3.5 4.5 4.5L6 12.5" />
                  </svg>
                </Link>
              );
            })}
          </nav>
          <nav className="account-actions" aria-label="账户操作">
            <a
              className="account-help"
              href="https://my.feishu.cn/docx/DdiCdPFcroUpUXxOumNcQpIin1g"
              target="_blank"
              rel="noreferrer"
            >
              <ProductIcon name="book" />
              产品使用手册
            </a>
            <Link className="account-settings" href="/settings">
              <ProductIcon name="settings" />
              个人设置
            </Link>
            <a className="account-logout" href="/api/auth/logout">
              <ProductIcon name="logout" />
              退出登录
            </a>
          </nav>
        </div>
      )}
    </div>
  );
}
