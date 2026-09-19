import { ActionIcon, Badge, Button, Card, Group, Modal, SimpleGrid, Stack, Text, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconPlus, IconX } from "@tabler/icons-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState, PageHeader } from "@/components/PageHeader";
import { StaffSelect } from "@/components/pickers";
import { staffName, useStaff, useTeams } from "@/components/staff";
import { QueryState } from "@/components/QueryState";
import { useApiMutation } from "@/components/useApiMutation";

export function TeamsPage() {
  const { can } = useAuth();
  const teams = useTeams();
  const staff = useStaff();
  const [creating, setCreating] = useState(false);
  const [adding, setAdding] = useState<Record<string, string | null>>({});
  const manage = can("assignments:manage");
  const invalidate = [["teams"], ["users"]];

  const addMember = useApiMutation({
    mutationFn: ({ teamId, userId }: { teamId: string; userId: string }) =>
      unwrap(api.POST("/api/v1/teams/{team_id}/members", { params: { path: { team_id: teamId } }, body: { user_id: userId } })),
    invalidate,
    success: "Added to the team",
    onSuccess: (_, v) => setAdding((a) => ({ ...a, [v.teamId]: null })),
  });
  const removeMember = useApiMutation({
    mutationFn: ({ teamId, userId }: { teamId: string; userId: string }) =>
      unwrap(api.DELETE("/api/v1/teams/{team_id}/members/{user_id}", { params: { path: { team_id: teamId, user_id: userId } } })),
    invalidate,
    success: "Removed from the team",
  });

  // Team membership comes with each staff user.
  const membersOf = (teamId: string) => (staff.data?.data ?? []).filter((u) => u.teams.some((t) => t.id === teamId));

  return (
    <>
      <PageHeader
        title="Teams"
        description="Assigning a patient to a team gives every team member access to that patient."
        actions={
          manage && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
              New team
            </Button>
          )
        }
      />
      <QueryState loading={teams.isPending || staff.isPending} error={teams.error ?? staff.error}>
        {teams.data?.length ? (
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            {teams.data.map((team) => {
              const members = membersOf(team.id);
              return (
                <Card key={team.id} withBorder>
                  <Group justify="space-between" mb="xs">
                    <Stack gap={0}>
                      <Title order={5}>{team.name}</Title>
                      <Text size="xs" c="dimmed">
                        {team.service ?? "No service set"} · {team.member_count} members
                      </Text>
                    </Stack>
                    {!team.active && <Badge color="gray">Inactive</Badge>}
                  </Group>
                  <Stack gap={4} mb="sm">
                    {members.map((m) => (
                      <Group key={m.id} justify="space-between">
                        <Text size="sm">
                          {staffName(m)}
                          <Text span size="xs" c="dimmed">
                            {m.profile.job_title && ` · ${m.profile.job_title}`}
                          </Text>
                        </Text>
                        {manage && (
                          <ActionIcon size="sm" variant="subtle" color="red" aria-label="Remove" onClick={() => removeMember.mutate({ teamId: team.id, userId: m.id })}>
                            <IconX size={14} />
                          </ActionIcon>
                        )}
                      </Group>
                    ))}
                    {members.length === 0 && (
                      <Text size="sm" c="dimmed">
                        No members yet.
                      </Text>
                    )}
                  </Stack>
                  {manage && (
                    <Group>
                      <StaffSelect
                        size="xs"
                        placeholder="Add a member"
                        value={adding[team.id] ?? null}
                        onChange={(v) => setAdding((a) => ({ ...a, [team.id]: v }))}
                        style={{ flex: 1 }}
                      />
                      <Button
                        size="xs"
                        disabled={!adding[team.id]}
                        onClick={() => addMember.mutate({ teamId: team.id, userId: adding[team.id]! })}
                      >
                        Add
                      </Button>
                    </Group>
                  )}
                </Card>
              );
            })}
          </SimpleGrid>
        ) : (
          <EmptyState>No teams yet.</EmptyState>
        )}
      </QueryState>
      <CreateTeamModal opened={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function CreateTeamModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const form = useForm({ initialValues: { name: "", service: "" }, validate: { name: (v) => (v.trim() ? null : "Required") } });
  const create = useApiMutation({
    mutationFn: (v: { name: string; service: string }) =>
      unwrap(api.POST("/api/v1/teams", { body: { name: v.name.trim(), service: v.service.trim() || null } })),
    invalidate: [["teams"]],
    success: "Team created",
    onSuccess: () => {
      form.reset();
      onClose();
    },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="New team">
      <form onSubmit={form.onSubmit((v) => create.mutate(v))}>
        <Stack>
          <TextInput label="Name" placeholder="District Nursing North" required {...form.getInputProps("name")} />
          <TextInput label="Service" placeholder="Community nursing" {...form.getInputProps("service")} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
