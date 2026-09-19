import { Button, Card, Checkbox, Group, Pagination, Select, Table, Text, TextInput } from "@mantine/core";
import { useDebouncedValue, useDisclosure } from "@mantine/hooks";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { PAGE_SIZE } from "@/utils/constants";
import { formatDate, fromNow, patientName } from "@/utils/format";

import { PatientFormModal } from "./PatientFormModal";

export function PatientsPage() {
  const { me, can } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search.trim(), 300);
  const [status, setStatus] = useState<string | null>(null);
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const [creating, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const term = debounced.length >= 2 ? debounced : null;

  // Search text goes in a POST body (never in the URL, where logs and proxies could keep it).
  const patients = useQuery({
    queryKey: ["patients", "list", term, status, mine, page],
    queryFn: () =>
      unwrap(
        api.POST("/api/v1/patients/search", {
          body: {
            search: term,
            status: status as "ACTIVE" | "INACTIVE" | "ARCHIVED" | null,
            assigned_staff_id: mine ? me!.id : null,
            sort: term ? "legal_last_name" : "-updated_at",
            page,
            page_size: PAGE_SIZE,
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const showDob = can("patients:read_sensitive");

  return (
    <>
      <PageHeader
        title="Patients"
        description={can("patients:read_all") ? "Everyone in your organisation." : "Patients assigned to you or your teams."}
        actions={
          can("patients:write") && (
            <Button leftSection={<IconPlus size={16} />} onClick={openCreate}>
              New patient
            </Button>
          )
        }
      />
      <Card withBorder mb="md">
        <Group>
          <TextInput
            placeholder={showDob ? "Search name, email, phone or MRN" : "Search name, email or phone"}
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(e) => {
              setSearch(e.currentTarget.value);
              setPage(1);
            }}
            style={{ flex: 1 }}
          />
          <Select
            placeholder="Active and inactive"
            data={[
              { value: "ACTIVE", label: "Active" },
              { value: "INACTIVE", label: "Inactive" },
              { value: "ARCHIVED", label: "Archived" },
            ]}
            value={status}
            onChange={(v) => {
              setStatus(v);
              setPage(1);
            }}
            clearable
            w={200}
          />
          <Checkbox label="Assigned to me" checked={mine} onChange={(e) => setMine(e.currentTarget.checked)} />
        </Group>
      </Card>
      <Card withBorder p={0}>
        <QueryState loading={patients.isPending} error={patients.error}>
          {patients.data?.data.length ? (
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Name</Table.Th>
                  {showDob && <Table.Th>Date of birth</Table.Th>}
                  <Table.Th>Phone</Table.Th>
                  <Table.Th>Email</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Updated</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {patients.data.data.map((p) => (
                  <Table.Tr key={p.id} style={{ cursor: "pointer" }} onClick={() => navigate(`/patients/${p.id}`)}>
                    <Table.Td fw={500}>{patientName(p)}</Table.Td>
                    {showDob && <Table.Td>{formatDate(p.date_of_birth)}</Table.Td>}
                    <Table.Td>{p.phone ?? "—"}</Table.Td>
                    <Table.Td>{p.email ?? "—"}</Table.Td>
                    <Table.Td>
                      <StatusBadge value={p.status} />
                    </Table.Td>
                    <Table.Td c="dimmed" fz="sm">
                      {fromNow(p.updated_at)}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          ) : (
            <EmptyState>{term ? "No patients match your search." : "No patients to show."}</EmptyState>
          )}
        </QueryState>
      </Card>
      {patients.data && patients.data.meta.total_pages > 1 && (
        <Group justify="space-between" mt="md">
          <Text size="sm" c="dimmed">
            {patients.data.meta.total} patients
          </Text>
          <Pagination total={patients.data.meta.total_pages} value={page} onChange={setPage} />
        </Group>
      )}
      <PatientFormModal opened={creating} onClose={closeCreate} onSaved={(p) => navigate(`/patients/${p.id}`)} />
    </>
  );
}
