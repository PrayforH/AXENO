"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { AuthUser, Membership } from "../lib/auth-session";

type AuthContextValue = {
  user: AuthUser;
  membership: Membership;
  passwordEnabled: boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<{
    user: AuthUser;
    membership: Membership;
    password_enabled: boolean;
  } | null>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/auth/session", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("unauthenticated");
        return (await response.json()) as {
          user: AuthUser;
          membership: Membership;
          password_enabled: boolean;
        };
      })
      .then((nextProfile) => {
        if (active) setProfile(nextProfile);
      })
      .catch(() => {
        if (active) window.location.replace("/login");
      });
    return () => {
      active = false;
    };
  }, []);

  const value = useMemo<AuthContextValue | null>(() => {
    if (!profile) return null;
    return {
      user: profile.user,
      membership: profile.membership,
      passwordEnabled: profile.password_enabled,
    };
  }, [profile]);

  if (!value) {
    return (
      <main className="auth-loading" aria-busy="true" aria-label="正在验证登录状态">
        <span className="auth-loading-mark">AS</span>
        <span>正在进入工作台…</span>
      </main>
    );
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
