import { Select, type SelectProps } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { patientName } from "@/utils/format";

import { staffName, useStaff, useTeams } from "./staff";

type PickerProps = Omit<SelectProps, "data">;

export function StaffSelect(props: PickerProps) {
  const staff = useStaff();
  const data = (staff.data?.data ?? []).map((u) => ({
    value: u.id,
    label: `${staffName(u)}${u.profile.job_title ? ` (${u.profile.job_title})` : ""}`,
  }));
  return <Select searchable clearable data={data} nothingFoundMessage="No staff found" {...props} />;
}

export function TeamSelect(props: PickerProps) {
  const teams = useTeams();
  const data = (teams.data ?? []).filter((t) => t.active).map((t) => ({ value: t.id, label: t.name }));
  return <Select searchable clearable data={data} nothingFoundMessage="No teams" {...props} />;
}

/** Search-as-you-type patient picker. The search text goes in a POST body, never the URL. */
export function PatientPicker({ initialLabel, ...props }: PickerProps & { initialLabel?: string }) {
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const term = debounced.trim().length >= 2 ? debounced.trim() : null;
  const results = useQuery({
    queryKey: ["patients", "picker", term],
    queryFn: () => unwrap(api.POST("/api/v1/patients/search", { body: { search: term, page_size: 20 } })),
  });
  const data = (results.data?.data ?? []).map((p) => ({ value: p.id, label: patientName(p) }));
  if (props.value && initialLabel && !data.some((d) => d.value === props.value)) {
    data.unshift({ value: props.value, label: initialLabel });
  }
  return (
    <Select
      searchable
      clearable
      data={data}
      searchValue={search}
      onSearchChange={setSearch}
      filter={({ options }) => options}
      nothingFoundMessage={results.isFetching ? "Searching…" : "No patients found"}
      {...props}
    />
  );
}
