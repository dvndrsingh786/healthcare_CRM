import { AppShell, Avatar, Burger, Group, Menu, NavLink, ScrollArea, Stack, Text, UnstyledButton } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconBuildingHospital, IconChevronDown, IconKey, IconLogout, IconUserCircle } from "@tabler/icons-react";
import { Link, Outlet, useLocation, useNavigate } from "react-router";

import { useAuth } from "@/auth/AuthContext";
import { NAV_ITEMS, type NavItem } from "./navigation";

function isActive(pathname: string, to: string) {
  return to === "/" ? pathname === "/" : pathname === to || pathname.startsWith(`${to}/`);
}

export function AppLayout() {
  const { me, logout } = useAuth();
  const [opened, { toggle, close }] = useDisclosure();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  if (!me) return null;

  const items = NAV_ITEMS.filter((item) => item.visible(me));
  const main = items.filter((item) => !item.section);
  const admin = items.filter((item) => item.section === "admin");

  const link = (item: NavItem) => (
    <NavLink
      key={item.to}
      component={Link}
      to={item.to}
      label={item.label}
      leftSection={item.icon}
      active={isActive(pathname, item.to)}
      onClick={close}
      variant="light"
    />
  );

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: !opened } }} padding="lg">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <IconBuildingHospital size={22} color="var(--mantine-color-teal-6)" />
            <Text fw={700}>Healthcare CRM</Text>
            <Text c="dimmed" size="sm" visibleFrom="sm">
              {me.organisation.name}
            </Text>
          </Group>
          <Menu position="bottom-end" width={220}>
            <Menu.Target>
              <UnstyledButton aria-label="Account menu">
                <Group gap="xs">
                  <Avatar size="sm" color="teal" radius="xl">
                    {(me.display_name ?? me.email).slice(0, 1).toUpperCase()}
                  </Avatar>
                  <Stack gap={0} visibleFrom="sm">
                    <Text size="sm" fw={500} lh={1.2}>
                      {me.display_name ?? me.email}
                    </Text>
                    <Text size="xs" c="dimmed" lh={1.2}>
                      {me.roles.join(", ")}
                    </Text>
                  </Stack>
                  <IconChevronDown size={14} />
                </Group>
              </UnstyledButton>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item leftSection={<IconUserCircle size={16} />} onClick={() => navigate("/account")}>
                My account
              </Menu.Item>
              <Menu.Item leftSection={<IconKey size={16} />} onClick={() => navigate("/account")}>
                Change password
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item leftSection={<IconLogout size={16} />} color="red" onClick={() => logout()}>
                Log out
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <ScrollArea>
          <Stack gap={2}>{main.map(link)}</Stack>
          {admin.length > 0 && (
            <>
              <Text size="xs" fw={700} c="dimmed" tt="uppercase" mt="lg" mb={4} px="sm">
                Administration
              </Text>
              <Stack gap={2}>{admin.map(link)}</Stack>
            </>
          )}
        </ScrollArea>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
