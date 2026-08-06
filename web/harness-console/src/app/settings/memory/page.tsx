"use client";

import { AuthProvider } from "../../../components/auth-provider";
import { MemoryBank } from "../../../components/memory-bank/memory-bank";

export default function MemorySettingsPage() {
  return <AuthProvider><MemoryBank /></AuthProvider>;
}
