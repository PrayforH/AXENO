import styles from "../../../components/agent-studio/agent-studio.module.css";
import { PRODUCT_NAME, ProductBrandMark } from "../../../components/product-brand";

export default function AgentStudioLoading() {
  return (
    <main className={styles.studioStateShell} aria-busy="true" aria-label={`正在加载${PRODUCT_NAME}`}>
      <section className={styles.studioStateCard}>
        <ProductBrandMark className={styles.studioStateMark} />
        <h1>正在恢复{PRODUCT_NAME}</h1>
        <p>正在读取草稿、已发布版本和有效运行契约。</p>
        <div className={styles.studioLoadingBars} aria-hidden="true">
          <i /><i /><i />
        </div>
      </section>
    </main>
  );
}
