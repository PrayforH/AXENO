import type { Metadata } from "next";
import { AuthProvider } from "../../../components/auth-provider";
import { TeamSpaces } from "../../../components/team-spaces/team-spaces";

export const metadata: Metadata = { title: "共享空间 · Agent Studio" };

export default function TeamSpacesPage() {
  return <AuthProvider><TeamSpaces /></AuthProvider>;
}
