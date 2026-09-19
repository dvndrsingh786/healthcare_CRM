import { ActionIcon, Button, Card, FileInput, Group, Modal, Select, SimpleGrid, Stack, Table, Text, TextInput, Title, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArchive, IconDownload, IconUpload } from "@tabler/icons-react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError, describeError, toApiError } from "@/api/errors";
import type { DocumentCategory, DocumentMeta, Patient, Visibility } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { EmptyState } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { ReasonModal } from "@/components/ReasonModal";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiMutation } from "@/components/useApiMutation";
import { DOCUMENT_CATEGORIES, UPLOAD_TYPES } from "@/utils/constants";
import { fileSize, formatDateTime, humanize, options } from "@/utils/format";

async function sha256(file: File) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Opens a short-lived signed download link. The API re-checks access when it is used. */
async function downloadDocument(documentId: string) {
  try {
    const link = await unwrap(api.POST("/api/v1/documents/{document_id}/download-link", { params: { path: { document_id: documentId } } }));
    // The link answers with "Content-Disposition: attachment", so the browser downloads the
    // file and stays on this page. (window.open after an await is often blocked as a popup.)
    window.location.assign(link.download_url);
  } catch (error) {
    notifications.show({ color: "red", title: "Download not possible", message: describeError(error) });
  }
}

export function DocumentsTab({ patient }: { patient: Patient }) {
  const { can } = useAuth();
  const [uploading, setUploading] = useState(false);
  const [archiving, setArchiving] = useState<DocumentMeta | null>(null);
  const documents = useQuery({
    queryKey: ["patient", patient.id, "documents"],
    queryFn: () =>
      unwrap(api.GET("/api/v1/patients/{patient_id}/documents", { params: { path: { patient_id: patient.id }, query: { page_size: 100 } } })),
  });
  const archive = useApiMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      unwrap(api.POST("/api/v1/documents/{document_id}/archive", { params: { path: { document_id: id } }, body: { reason } })),
    invalidate: [["patient", patient.id]],
    success: "Document archived (kept on record)",
    onSuccess: () => setArchiving(null),
  });

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Title order={5}>Documents</Title>
        {can("documents:write") && patient.status !== "ARCHIVED" && (
          <Button size="xs" variant="light" leftSection={<IconUpload size={14} />} onClick={() => setUploading(true)}>
            Upload
          </Button>
        )}
      </Group>
      <Text size="xs" c="dimmed" mb="sm">
        Files are stored privately. Downloads use a link that works for a few minutes and checks your access again.
      </Text>
      <QueryState loading={documents.isPending} error={documents.error}>
        {documents.data?.data.length ? (
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Document</Table.Th>
                <Table.Th>Category</Table.Th>
                <Table.Th>Who can see it</Table.Th>
                <Table.Th>Uploaded</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {documents.data.data.map((d) => (
                <Table.Tr key={d.id}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {d.title ?? d.original_filename}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {d.original_filename} · {fileSize(d.size_bytes)}
                    </Text>
                  </Table.Td>
                  <Table.Td>{humanize(d.category)}</Table.Td>
                  <Table.Td>
                    <StatusBadge value={d.visibility} size="xs" />
                  </Table.Td>
                  <Table.Td>
                    {d.status === "AVAILABLE" ? formatDateTime(d.uploaded_at) : <StatusBadge value={d.status} size="xs" />}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      {d.status === "AVAILABLE" && (
                        <Tooltip label="Download">
                          <ActionIcon variant="light" aria-label="Download" onClick={() => downloadDocument(d.id)}>
                            <IconDownload size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      {can("documents:write") && (
                        <Tooltip label="Archive">
                          <ActionIcon variant="subtle" color="red" aria-label="Archive" onClick={() => setArchiving(d)}>
                            <IconArchive size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <EmptyState>No documents you can see.</EmptyState>
        )}
      </QueryState>
      <UploadModal patientId={patient.id} opened={uploading} onClose={() => setUploading(false)} />
      <ReasonModal
        opened={!!archiving}
        title="Archive document"
        label="Why? (the file is kept under the retention policy)"
        confirmLabel="Archive"
        loading={archive.isPending}
        onClose={() => setArchiving(null)}
        onConfirm={(reason) => archiving && archive.mutate({ id: archiving.id, reason })}
      />
    </Card>
  );
}

function UploadModal({ patientId, opened, onClose }: { patientId: string; opened: boolean; onClose: () => void }) {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<string | null>("LETTER");
  const [visibility, setVisibility] = useState<string | null>("INTERNAL");
  const [step, setStep] = useState<string | null>(null);

  const close = () => {
    setFile(null);
    setTitle("");
    setStep(null);
    onClose();
  };

  const upload = async () => {
    if (!file) return;
    const mime = file.type;
    if (!UPLOAD_TYPES[mime]) {
      notifications.show({ color: "red", message: "Only PDF, PNG and JPEG files can be uploaded." });
      return;
    }
    try {
      setStep("Preparing upload…");
      const intent = await unwrap(
        api.POST("/api/v1/patients/{patient_id}/documents", {
          params: { path: { patient_id: patientId } },
          body: {
            original_filename: file.name,
            mime_type: mime as "application/pdf" | "image/png" | "image/jpeg",
            size_bytes: file.size,
            category: category as DocumentCategory,
            visibility: visibility as Visibility,
            title: title.trim() || null,
          },
        }),
      );
      setStep("Uploading…");
      const put = await fetch(intent.upload_url, { method: "PUT", headers: { "Content-Type": mime }, body: file });
      if (!put.ok) throw toApiError(put.status, await put.json().catch(() => undefined));
      setStep("Checking the file…");
      await unwrap(
        api.POST("/api/v1/documents/{document_id}/confirm", {
          params: { path: { document_id: intent.document.id } },
          body: { checksum_sha256: await sha256(file) },
        }),
      );
      notifications.show({ color: "green", message: "Document uploaded" });
      await queryClient.invalidateQueries({ queryKey: ["patient", patientId] });
      close();
    } catch (error) {
      const message =
        error instanceof ApiError && error.code === "FILE_REJECTED"
          ? `${error.message} The file does not look like a real ${mime.split("/")[1].toUpperCase()}.`
          : describeError(error);
      notifications.show({ color: "red", title: "Upload failed", message, autoClose: 10000 });
      setStep(null);
      await queryClient.invalidateQueries({ queryKey: ["patient", patientId, "documents"] });
    }
  };

  const visibilityOptions = ["INTERNAL", "APP_VISIBLE", ...(can("notes:read_clinical") ? ["CLINICAL"] : [])];
  return (
    <Modal opened={opened} onClose={close} title="Upload document">
      <Stack>
        <FileInput
          label="File"
          placeholder="PDF, PNG or JPEG, up to 10 MB"
          accept={Object.keys(UPLOAD_TYPES).join(",")}
          value={file}
          onChange={setFile}
          clearable
          required
        />
        <TextInput label="Title" placeholder="Optional, e.g. GP referral letter" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
        <SimpleGrid cols={2}>
          <Select label="Category" data={options(DOCUMENT_CATEGORIES)} value={category} onChange={setCategory} />
          <Select
            label="Who can see it"
            data={visibilityOptions.map((v) => ({ value: v, label: humanize(v) }))}
            value={visibility}
            onChange={setVisibility}
          />
        </SimpleGrid>
        {visibility === "APP_VISIBLE" && (
          <Text size="xs" c="dimmed">
            The patient can download it in their app and is notified.
          </Text>
        )}
        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            {step}
          </Text>
          <Group>
            <Button variant="default" onClick={close} disabled={!!step}>
              Cancel
            </Button>
            <Button onClick={upload} loading={!!step} disabled={!file}>
              Upload
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
