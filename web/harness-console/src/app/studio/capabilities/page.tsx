import type { Metadata } from "next";
import { AuthProvider } from "../../../components/auth-provider";
import { McpCatalogControlPlane } from "../../../components/agent-studio/mcp-catalog-control-plane";

export const metadata: Metadata = { title: "MCP 能力目录" };

export default function StudioCapabilitiesPage() {
  return (
    <AuthProvider>
      <McpCatalogControlPlane />
    </AuthProvider>
  );
}
