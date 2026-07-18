import type { Metadata } from "next";
import { AuthProvider } from "../../../components/auth-provider";
import { DataLifecycleControlPlane } from "../../../components/agent-studio/data-lifecycle-control-plane";

export const metadata: Metadata = { title: "数据生命周期" };

export default function StudioDataPage() {
  return <AuthProvider><DataLifecycleControlPlane /></AuthProvider>;
}
