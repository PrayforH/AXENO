import type { Metadata } from "next";
import { AuthProvider } from "../../../components/auth-provider";
import { QuotaControlPlane } from "../../../components/agent-studio/quota-control-plane";

export const metadata: Metadata = { title: "使用量与配额" };

export default function StudioUsagePage() {
  return <AuthProvider><QuotaControlPlane /></AuthProvider>;
}
