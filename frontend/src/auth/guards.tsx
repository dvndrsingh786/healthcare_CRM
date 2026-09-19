import { Center, Loader } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import type { Me } from "@/api/types";
import { homePath } from "@/components/navigation";

import { useAuth } from "./AuthContext";

/** Only for logged-in users; everyone else goes to the login page. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (!me) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

/** A page for some roles only. Others are sent to their own start page.
 *  (The API refuses the data anyway; this just avoids showing an empty, broken page.) */
export function RequirePage({ allow, children }: { allow: (me: Me) => boolean; children: ReactNode }) {
  const { me } = useAuth();
  if (!me) return null;
  if (!allow(me)) return <Navigate to={homePath(me)} replace />;
  return <>{children}</>;
}
