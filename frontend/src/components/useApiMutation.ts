import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { describeError } from "@/api/errors";

interface Options<TData, TVars> {
  mutationFn: (vars: TVars) => Promise<TData>;
  /** Query keys to refresh after success (prefix match). */
  invalidate?: QueryKey[];
  success?: string | ((data: TData) => string);
  onSuccess?: (data: TData, vars: TVars) => void;
  /** Handle an error yourself (return true) instead of the default error toast. */
  onError?: (error: unknown) => boolean | void;
}

/** useMutation + success toast + error toast with the API's message + cache refresh. */
export function useApiMutation<TData, TVars = void>({ mutationFn, invalidate = [], success, onSuccess, onError }: Options<TData, TVars>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async (data, vars) => {
      await Promise.all(invalidate.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      if (success) {
        notifications.show({ color: "green", message: typeof success === "function" ? success(data) : success });
      }
      onSuccess?.(data, vars);
    },
    onError: (error) => {
      if (onError?.(error)) return;
      notifications.show({ color: "red", title: "Not saved", message: describeError(error), autoClose: 8000 });
    },
  });
}
