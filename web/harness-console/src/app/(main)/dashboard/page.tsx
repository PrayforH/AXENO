"use client";

import { useEffect, useState } from "react";

interface RunInfo {
  run_id: string;
  session_id: string;
  status: string;
  created_at: string;
  updated_at: string;
}

interface DashboardStats {
  totalRuns: number;
  succeededRuns: number;
  failedRuns: number;
}

export default function DashboardPage() {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [stats, setStats] = useState<DashboardStats>({
    totalRuns: 0,
    succeededRuns: 0,
    failedRuns: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/harness/runs?limit=100");
        if (!res.ok) throw new Error(await res.text());
        const data: RunInfo[] = await res.json();
        setRuns(data);
        const succeeded = data.filter((r) => r.status === "succeeded").length;
        const failed = data.filter(
          (r) => r.status === "failed" || r.status === "timed_out" || r.status === "rejected"
        ).length;
        setStats({
          totalRuns: data.length,
          succeededRuns: succeeded,
          failedRuns: failed,
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const statusLabels: Record<string, string> = {
    queued: "排队中",
    provisioning: "准备中",
    running: "运行中",
    waiting_approval: "等待审批",
    cancelling: "取消中",
    cancelled: "已取消",
    succeeded: "已完成",
    failed: "失败",
    timed_out: "已超时",
    rejected: "已拒绝",
  };

  if (loading) {
    return (
      <div className="page-container">
        <h1>运行仪表板</h1>
        <p>加载中...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-container">
        <h1>运行仪表板</h1>
        <p className="error-message">{error}</p>
      </div>
    );
  }

  return (
    <div className="page-container">
      <header className="page-header">
        <h1>运行仪表板</h1>
      </header>

      <div className="stats-grid">
        <div className="stat-tile">
          <span className="stat-number">{stats.totalRuns}</span>
          <small>总运行数</small>
        </div>
        <div className="stat-tile stat-success">
          <span className="stat-number">{stats.succeededRuns}</span>
          <small>成功</small>
        </div>
        <div className="stat-tile stat-danger">
          <span className="stat-number">{stats.failedRuns}</span>
          <small>失败</small>
        </div>
      </div>

      {runs.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">📊</span>
          <strong>还没有运行记录</strong>
          <p>开始一个对话任务后，运行记录将显示在这里。</p>
        </div>
      ) : (
        <div className="run-table-container">
          <table className="run-table">
            <thead>
              <tr>
                <th>运行 ID</th>
                <th>状态</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <td>
                    <code>{run.run_id.slice(0, 16)}...</code>
                  </td>
                  <td>
                    <span className={`status-badge status-${run.status}`}>
                      {statusLabels[run.status] ?? run.status}
                    </span>
                  </td>
                  <td>
                    <time>
                      {new Date(run.created_at).toLocaleString("zh-CN")}
                    </time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
