import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, onSessionEnded, refreshOnce, unwrap } from "@/api/client";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "@/api/tokens";
import type { Me } from "@/api/types";

import { hasPermission, type Permission } from "./permissions";

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: (everywhere?: boolean) => Promise<void>;
  can: (permission: Permission) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  // After a reload only the refresh token survives, so get a fresh access token first.
  const [restored, setRestored] = useState(() => !!getAccessToken() || !getRefreshToken());
  const [signedIn, setSignedIn] = useState(() => !!getAccessToken() || !!getRefreshToken());

  useEffect(() => {
    if (restored) return;
    refreshOnce().then((ok) => {
      setSignedIn(ok);
      setRestored(true);
    });
  }, [restored]);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => unwrap(api.GET("/api/v1/auth/me")),
    enabled: restored && signedIn,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const endSession = useCallback(() => {
    clearTokens();
    setSignedIn(false);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => onSessionEnded(endSession), [endSession]);

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await unwrap(api.POST("/api/v1/auth/login", { body: { email, password } }));
      if (tokens.scope !== "crm") {
        // Patients use the patient app, not this staff CRM.
        await fetch("/api/v1/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${tokens.access_token}` } });
        throw new Error("This is the staff CRM. Patients sign in through the patient app.");
      }
      setTokens(tokens.access_token, tokens.refresh_token);
      queryClient.clear();
      setSignedIn(true);
    },
    [queryClient],
  );

  const logout = useCallback(
    async (everywhere = false) => {
      try {
        await api.POST(everywhere ? "/api/v1/auth/logout-all" : "/api/v1/auth/logout");
      } finally {
        endSession();
      }
    },
    [endSession],
  );

  const me = signedIn ? (meQuery.data ?? null) : null;
  const value = useMemo<AuthState>(
    () => ({
      me,
      loading: !restored || (signedIn && meQuery.isPending),
      login,
      logout,
      can: (permission) => hasPermission(me, permission),
    }),
    [me, restored, signedIn, meQuery.isPending, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// The provider and its hook belong together (standard React context pattern).
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
