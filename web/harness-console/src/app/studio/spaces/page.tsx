import type { Metadata } from "next";
import { AuthProvider } from "../../../components/auth-provider";
import { TeamSpaces } from "../../../components/team-spaces/team-spaces";

export const metadata: Metadata = { title: "协作空间" };

export default function TeamSpacesPage() {
  return <AuthProvider><TeamSpaces /></AuthProvider>;
}
