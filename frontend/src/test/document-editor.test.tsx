import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { DocumentEditor } from "@/pages/artifacts/DocumentEditor";
import {
  getDocumentDraft,
  saveDocumentDraft,
  publishDocument,
  type DocumentDraft,
} from "@/api/careerWorkspace";
import { listArtifactVersions } from "@/api/artifacts";

vi.mock("@/api/careerWorkspace", () => ({
  getDocumentDraft: vi.fn(),
  saveDocumentDraft: vi.fn(),
  publishDocument: vi.fn(),
  downloadText: vi.fn(),
}));
vi.mock("@/api/artifacts", () => ({ listArtifactVersions: vi.fn() }));
vi.mock("@/pages/career/useCareerWorkspace", () => ({
  useRefreshCareer: () => async () => {},
  careerError: vi.fn(),
}));
const initial: DocumentDraft = {
  artifact_id: "doc",
  kind: "resume",
  archived: false,
  awaiting_extraction: false,
  revision: 0,
  base_version_id: "v1",
  current_version_id: "v1",
  title: "我的简历",
  updated_at: "2026-10-15T00:00:00Z",
  data: {
    schema_version: 1,
    name: "原姓名",
    headline: "",
    contact: "",
    summary: "当前内容",
    sections: [],
    template: "classic",
    accent: "forest",
    font_size: 11,
  },
};
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(getDocumentDraft).mockResolvedValue(initial);
  vi.mocked(listArtifactVersions).mockResolvedValue([]);
  vi.mocked(saveDocumentDraft).mockImplementation(async (_, body) => ({
    ...initial,
    ...body,
    revision: body.expected_revision + 1,
  }));
});
function show(path = "/") {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <DocumentEditor id="doc" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("preserves failed edits and rebases only after the user compares server content", async () => {
  vi.mocked(saveDocumentDraft).mockRejectedValueOnce(
    new Error("草稿已在别处更新"),
  );
  show();
  const name = await screen.findByLabelText("姓名 / 标题");
  fireEvent.change(name, { target: { value: "设备上的修改" } });
  await screen.findByRole(
    "button",
    { name: "比较服务器版本" },
    { timeout: 2500 },
  );
  expect(name).toHaveValue("设备上的修改");
  const remote = {
    ...initial,
    revision: 7,
    base_version_id: "v2",
    current_version_id: "v2",
    data: { ...initial.data, name: "另一窗口修改" },
  };
  vi.mocked(getDocumentDraft).mockResolvedValue(remote);
  fireEvent.click(screen.getByRole("button", { name: "比较服务器版本" }));
  await screen.findByRole("dialog");
  expect(screen.getByText(/另一窗口修改/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "继续保存本设备内容" }));
  await waitFor(
    () =>
      expect(saveDocumentDraft).toHaveBeenLastCalledWith(
        "doc",
        expect.objectContaining({
          expected_revision: 7,
          base_version_id: "v2",
          data: expect.objectContaining({ name: "设备上的修改" }),
        }),
      ),
    { timeout: 2500 },
  );
});

it("locks editing during formal publication and retains a single publication request", async () => {
  let finish!: (value: DocumentDraft) => void;
  vi.mocked(publishDocument).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  show();
  const name = await screen.findByLabelText("姓名 / 标题");
  fireEvent.click(screen.getByRole("button", { name: "保存正式版本" }));
  await waitFor(() => expect(publishDocument).toHaveBeenCalledTimes(1));
  expect(name).toBeDisabled();
  finish({
    ...initial,
    revision: 2,
    base_version_id: "v2",
    current_version_id: "v2",
  });
  await waitFor(() => expect(name).not.toBeDisabled());
});

it("opens an exact historical submission without substituting current content", async () => {
  vi.mocked(listArtifactVersions).mockResolvedValue([
    {
      id: "submitted",
      artifact_id: "doc",
      version_no: 1,
      title: "投递时的简历",
      document_json: { ...initial.data, summary: "投递时的原文" },
      content_text: "投递时的原文",
      created_at: initial.updated_at,
      content_format: "markdown",
      file_asset_id: null,
      file_asset_version: null,
      origin_kind: "edit",
      source_message_id: null,
      source_turn_id: null,
      source_owner_type: null,
      source_owner_id: null,
    },
  ]);
  show("/?version=submitted");
  await screen.findByText("投递时的原文");
  expect(screen.queryByText("当前内容")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "保存正式版本" }),
  ).not.toBeInTheDocument();
  expect(saveDocumentDraft).not.toHaveBeenCalled();
});
