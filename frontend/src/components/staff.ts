import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";

/** Active staff of the organisation (for owner / assignee pickers and team lists). */
export function useStaff() {
  return useQuery({
    queryKey: ["users", "staff-options"],
    queryFn: () =>
      unwrap(api.GET("/api/v1/users", { params: { query: { user_type: "STAFF", status: "ACTIVE", page_size: 100 } } })),
    staleTime: 60_000,
  });
}

export function useTeams() {
  return useQuery({ queryKey: ["teams"], queryFn: () => unwrap(api.GET("/api/v1/teams")), staleTime: 60_000 });
}

export function staffName(staff: { email: string; profile: { display_name: string | null } }) {
  return staff.profile.display_name ?? staff.email;
}
