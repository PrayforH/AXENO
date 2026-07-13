"use client";

import { CopilotKitInspector } from "@copilotkit/react-core/v2";
import { developerRows } from "../lib/developer-details";

export function DeveloperDrawer({ threadId }: { threadId: string }) {
  return (
    <aside className="developer-drawer" aria-label="运行详情">
      <div className="developer-grid">
        {developerRows(threadId).map(([label, value]) => (
          <div className="developer-row" key={label}>
            <span>{label}</span>
            <code>{value}</code>
          </div>
        ))}
      </div>
      <p>
        AG-UI 事件、消息和状态可在 CopilotKit Inspector 中查看；身份头仅保留在服务端。
      </p>
      <CopilotKitInspector />
    </aside>
  );
}
