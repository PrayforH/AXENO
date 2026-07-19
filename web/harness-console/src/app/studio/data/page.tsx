import type { Metadata } from "next";
import { AuthProvider } from "../../../components/auth-provider";
import { DataLifecycleControlPlane } from "../../../components/agent-studio/data-lifecycle-control-plane";

export const metadata: Metadata = { title: "知识与数据" };

export default function StudioDataPage() {
  return <AuthProvider><DataLifecycleControlPlane /></AuthProvider>;
}
