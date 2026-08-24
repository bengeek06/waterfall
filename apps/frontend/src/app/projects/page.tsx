"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ProjectsTable } from "@/components/projects-table";
import {
  ApiError,
  Project,
  SessionExpiredError,
  createProject,
  deleteProject,
  getMe,
  getProjects,
  restoreSession,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

const PROJECT_PAGE_SIZE = 50;

export default function ProjectsPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectOffset, setProjectOffset] = useState(0);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [createMode, setCreateMode] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createCode, setCreateCode] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const onSessionRefresh = useMemo(
    () => (next: SessionTokens) => {
      setSession(next);
      setSessionState(next);
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!session) {
        try {
          const restoredSession = await restoreSession();
          if (cancelled) {
            return;
          }
          setSession(restoredSession);
          setSessionState(restoredSession);
        } catch {
          clearSession();
          router.push("/login");
        }
        return;
      }
      setBusy(true);
      setError(null);
      try {
        await getMe(session, onSessionRefresh);
        const projectsData = await getProjects(
          session,
          onSessionRefresh,
          PROJECT_PAGE_SIZE,
          projectOffset,
          includeArchived,
        );
        if (cancelled) {
          return;
        }
        setProjects(projectsData);
        setSelectedIds(new Set());
      } catch (cause) {
        if (cancelled) {
          return;
        }
        if (cause instanceof SessionExpiredError) {
          clearSession();
          router.push("/login");
          return;
        }
        if (cause instanceof ApiError) {
          if (cause.status === 401) {
            clearSession();
            router.push("/login");
            return;
          }
          setError(cause.message);
        } else {
          setError("Erreur inattendue lors du chargement des projets");
        }
      } finally {
        if (!cancelled) {
          setBusy(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [includeArchived, onSessionRefresh, projectOffset, router, session]);

  function toggleIncludeArchived() {
    setIncludeArchived((current) => !current);
    setProjectOffset(0);
    setSelectedIds(new Set());
  }

  function resetCreateFlow() {
    setCreateMode(false);
    setCreateName("");
    setCreateCode("");
    setCreateDescription("");
  }

  async function onCreateProject() {
    if (!session) {
      router.push("/login");
      return;
    }
    if (!createName.trim() || !createCode.trim()) {
      setError("Le nom et le code du projet sont obligatoires.");
      return;
    }

    setError(null);
    setActionBusy("Création du projet en cours...");
    try {
      const project = await createProject(
        {
          name: createName.trim(),
          code: createCode.trim(),
          short_description: createDescription.trim() || null,
        },
        session,
        onSessionRefresh,
      );
      setProjects((prev) => [...prev, project].sort((left, right) => left.id - right.id));
      resetCreateFlow();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Impossible de créer le projet.");
    } finally {
      setActionBusy(null);
    }
  }

  async function onDeleteSelected() {
    if (!session || selectedIds.size === 0) {
      return;
    }

    const projectIds = [...selectedIds];
    setActionBusy("Suppression des projets sélectionnés...");
    try {
      for (const projectId of projectIds) {
        await deleteProject(projectId, session, onSessionRefresh);
      }
      setProjects((prev) => prev.filter((project) => !projectIds.includes(project.id)));
      setSelectedIds(new Set());
      toast.success(`${projectIds.length} projet(s) supprimé(s).`);
    } catch (cause) {
      toast.error(cause instanceof ApiError ? cause.message : "Impossible de supprimer les projets.");
    } finally {
      setActionBusy(null);
    }
  }

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 className="title">Gestion des projets</h1>
          </div>
        </div>

        <div className="row" style={{ marginTop: "1rem" }}>
          {!createMode ? (
            <button className="btn btn-primary" type="button" onClick={() => setCreateMode(true)}>
              Créer projet
            </button>
          ) : null}
        </div>

        <label className="checkbox-label" style={{ marginTop: "1rem" }}>
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={toggleIncludeArchived}
          />
          Inclure les projets perdus, terminés ou abandonnés
        </label>

        {createMode ? (
          <div className="panel" style={{ marginTop: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>Nouveau projet</h2>

            <div className="field">
              <label htmlFor="project-name">Nom du projet</label>
              <input
                id="project-name"
                type="text"
                value={createName}
                onChange={(event) => setCreateName(event.target.value)}
                placeholder="Ex: Projet pilote"
                maxLength={255}
              />
            </div>
            <div className="field">
              <label htmlFor="project-code">Code projet</label>
              <input
                id="project-code"
                type="text"
                value={createCode}
                onChange={(event) => setCreateCode(event.target.value)}
                placeholder="Ex: PRJ-001"
                maxLength={64}
              />
            </div>
            <div className="field">
              <label htmlFor="project-description">Description (facultatif)</label>
              <textarea
                id="project-description"
                rows={2}
                value={createDescription}
                onChange={(event) => setCreateDescription(event.target.value)}
                maxLength={500}
              />
            </div>
            <div className="row" style={{ marginTop: "0.8rem" }}>
              <button
                className="btn btn-primary"
                type="button"
                disabled={Boolean(actionBusy)}
                onClick={() => void onCreateProject()}
              >
                Créer
              </button>
              <button className="btn" type="button" onClick={resetCreateFlow}>
                Annuler
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel">
        {busy ? <p className="muted" role="status">Chargement...</p> : null}
        {actionBusy ? <p className="muted" role="status">{actionBusy}</p> : null}
        {error ? <p className="error" role="alert">{error}</p> : null}

        {!busy && !projects.length ? <p className="muted">Aucun projet importé.</p> : null}

        {!busy && projects.length ? (
          <>
            <div className="row" style={{ marginBottom: "0.8rem", justifyContent: "space-between" }}>
              <span className="muted">
                {selectedIds.size ? `${selectedIds.size} sélectionné(s)` : ""}
              </span>
              <button
                className="btn btn-danger"
                type="button"
                disabled={!selectedIds.size || Boolean(actionBusy)}
                onClick={() => setDeleteDialogOpen(true)}
              >
                Supprimer la sélection
              </button>
            </div>
            <ProjectsTable
              projects={projects}
              selectedIds={selectedIds}
              onSelectedIdsChange={setSelectedIds}
              onProjectOpen={(projectId) => router.push(`/projects/${projectId}`)}
            />
          </>
        ) : null}

        {!busy ? (
          <div className="row" style={{ marginTop: "1rem", justifyContent: "space-between" }}>
            <span className="muted">
              {projects.length ? `Projets ${projectOffset + 1} à ${projectOffset + projects.length}` : ""}
            </span>
            <div className="row">
              <button
                className="btn"
                type="button"
                disabled={projectOffset === 0}
                onClick={() => setProjectOffset((current) => Math.max(0, current - PROJECT_PAGE_SIZE))}
              >
                Précédent
              </button>
              <button
                className="btn"
                type="button"
                disabled={projects.length < PROJECT_PAGE_SIZE}
                onClick={() => setProjectOffset((current) => current + PROJECT_PAGE_SIZE)}
              >
                Suivant
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Supprimer les projets sélectionnés ?</AlertDialogTitle>
            <AlertDialogDescription>
              {selectedIds.size} projet(s) seront supprimé(s) définitivement. Cette action est irréversible.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                setDeleteDialogOpen(false);
                void onDeleteSelected();
              }}
            >
              Supprimer
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
