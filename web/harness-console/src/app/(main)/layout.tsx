import { Sidebar } from "../../components/sidebar/sidebar";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">{children}</main>
    </div>
  );
}
