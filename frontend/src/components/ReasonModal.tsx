import { Button, Group, Modal, Textarea } from "@mantine/core";
import { useState } from "react";

interface Props {
  opened: boolean;
  title: string;
  label?: string;
  confirmLabel?: string;
  color?: string;
  loading?: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}

/** Asks for a short reason (cancel, archive, retract...). The API requires one for these actions. */
export function ReasonModal({ opened, title, label = "Reason", confirmLabel = "Confirm", color = "red", loading, onClose, onConfirm }: Props) {
  const [reason, setReason] = useState("");
  const close = () => {
    setReason("");
    onClose();
  };
  return (
    <Modal opened={opened} onClose={close} title={title}>
      <Textarea
        label={label}
        value={reason}
        onChange={(e) => setReason(e.currentTarget.value)}
        minRows={2}
        maxLength={255}
        required
        data-autofocus
      />
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={close}>
          Back
        </Button>
        <Button
          color={color}
          loading={loading}
          disabled={reason.trim().length < 3}
          onClick={() => {
            onConfirm(reason.trim());
            setReason("");
          }}
        >
          {confirmLabel}
        </Button>
      </Group>
    </Modal>
  );
}
