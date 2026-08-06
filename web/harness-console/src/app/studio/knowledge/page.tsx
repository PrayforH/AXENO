import type { Metadata } from "next";
import { McpCatalogControlPlane } from "../../../components/agent-studio/mcp-catalog-control-plane";
import { AuthProvider } from "../../../components/auth-provider";

export const metadata: Metadata = { title: "外部知识库 · Agent Studio" };

export default function KnowledgePage() {
  return (
    <AuthProvider>
      <McpCatalogControlPlane mode="knowledge" />
    </AuthProvider>
  );
}
