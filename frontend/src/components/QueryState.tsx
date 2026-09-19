import { Alert, Center, Loader } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import type { ReactNode } from "react";

import { describeError } from "@/api/errors";

/** Shows a loader while loading, an error box on failure, otherwise the children. */
export function QueryState({ loading, error, children }: { loading: boolean; error: unknown; children: ReactNode }) {
  if (loading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (error) {
    return (
      <Alert color="red" icon={<IconAlertTriangle size={18} />} title="Could not load this">
        {describeError(error)}
      </Alert>
    );
  }
  return <>{children}</>;
}
