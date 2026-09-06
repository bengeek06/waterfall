import { useState } from "react";
import type { useRouter } from "next/navigation";

import { ApiError, Project, SessionExpiredError, updateProject } from "@/lib/backend";
import { clearSession, type SessionTokens } from "@/lib/session";

type AppRouter = ReturnType<typeof useRouter>;

export type ProjectInfoDraft = { name: string; shortDescription: string };

interface UseProjectInfoEditorParams {
  session: SessionTokens | null;
  project: Project | null;
  projectId: number;
  onSessionRefresh: (next: SessionTokens) => void;
  router: AppRouter;
  setProject: (project: Project) => void;
  setError: (message: string | null) => void;
}

// Extracted from ProjectDetailsPage (E4-11 / #151): owns the project-info inline-edit state
// (name/short description) and its save handler. Pure mechanical move -- see page.tsx call site
// (header card "Modifier" flow) for wiring.
export function useProjectInfoEditor({
  session,
  project,
  projectId,
  onSessionRefresh,
  router,
  setProject,
  setError,
}: UseProjectInfoEditorParams) {
  const [editingProjectInfo, setEditingProjectInfo] = useState(false);
  const [projectInfoDraft, setProjectInfoDraft] = useState<ProjectInfoDraft>({ name: "", shortDescription: "" });
  const [projectInfoBusy, setProjectInfoBusy] = useState(false);

  function startEditProjectInfo() {
    if (!project) {
      return;
    }
    setProjectInfoDraft({ name: project.name, shortDescription: project.short_description ?? "" });
    setEditingProjectInfo(true);
  }

  function cancelEditProjectInfo() {
    setEditingProjectInfo(false);
  }

  function updateProjectInfoName(value: string) {
    setProjectInfoDraft((prev) => ({ ...prev, name: value }));
  }

  function updateProjectInfoDescription(value: string) {
    setProjectInfoDraft((prev) => ({ ...prev, shortDescription: value }));
  }

  async function saveProjectInfo() {
    if (!session || !project) {
      return;
    }
    if (!projectInfoDraft.name.trim()) {
      setError("Le nom du projet est obligatoire.");
      return;
    }

    setProjectInfoBusy(true);
    setError(null);
    try {
      const updated = await updateProject(
        projectId,
        {
          name: projectInfoDraft.name.trim(),
          short_description: projectInfoDraft.shortDescription.trim() || null,
        },
        session,
        onSessionRefresh,
      );
      setProject(updated);
      setEditingProjectInfo(false);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de modifier le projet.");
    } finally {
      setProjectInfoBusy(false);
    }
  }

  return {
    editingProjectInfo,
    projectInfoDraft,
    projectInfoBusy,
    startEditProjectInfo,
    cancelEditProjectInfo,
    updateProjectInfoName,
    updateProjectInfoDescription,
    saveProjectInfo,
  };
}
