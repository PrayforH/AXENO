import styles from "../../../components/agent-studio/agent-studio.module.css";

export default function AgentStudioLoading() {
  return (
    <main className={styles.studioStateShell} aria-busy="true" aria-label="正在加载 Agent Studio">
      <section className={styles.studioStateCard}>
        <span className={styles.studioStateMark} data-tone="loading" aria-hidden="true">AS</span>
        <h1>正在恢复 Agent Studio</h1>
        <p>正在读取草稿、已发布版本和有效运行契约。</p>
        <div className={styles.studioLoadingBars} aria-hidden="true">
          <i /><i /><i />
        </div>
      </section>
    </main>
  );
}
