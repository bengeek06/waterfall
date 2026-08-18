"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  ApiError,
  AuthUser,
  Project,
  SessionExpiredError,
  createImportBatch,
  createProject,
  deleteProject,
  getImportBatchStatus,
  getMe,
  getProjects,
  exportProjectXml,
  runImportBatch,
  updateProjectName,
  uploadImportSourceXml,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

const MAX_IMPORT_FILE_SIZE = 25 * 1024 * 1024;
const PROJECT_PAGE_SIZE = 50;

export default function ProjectsPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [me, setMe] = useState<AuthUser | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectOffset, setProjectOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [createMode, setCreateMode] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createStep, setCreateStep] = useState<"name" | "file">("name");
  const [createFile, setCreateFile] = useState<File | null>(null);
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState("");

  const onSessionRefresh = useMemo(
    () => (next: SessionTokens) => {
      setSession(next);
      setSessionState(next);
    },
    [],
  );

  useEffect(() => {
    async function load() {
      if (!session) {
        router.push("/login");
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const meData = await getMe(session, onSessionRefresh);
        setMe(meData);
        const projectsData = await getProjects(
          session,
          onSessionRefresh,
          PROJECT_PAGE_SIZE,
          projectOffset,
        );
        setProjects(projectsData);
      } catch (cause) {
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
        setBusy(false);
      }
    }

    void load();
  }, [onSessionRefresh, projectOffset, router, session]);

  async function refreshProjects(activeSession: SessionTokens) {
    const projectsData = await getProjects(
      activeSession,
      onSessionRefresh,
      PROJECT_PAGE_SIZE,
      projectOffset,
    );
    setProjects(projectsData);
  }

  function resetCreateFlow() {
    setCreateMode(false);
    setCreateName("");
    setCreateStep("name");
    setCreateFile(null);
  }

  async function onCreateContinue() {
    if (!createName.trim()) {
      setError("Le nom du projet est obligatoire.");
      return;
    }
    setCreateStep("file");
  }

  async function onCreateManualProject() {
    if (!session) {
      router.push("/login");
      return;
    }
    if (!createName.trim()) {
      setError("Le nom du projet est obligatoire.");
      return;
    }

    setError(null);
    setActionBusy("Création du projet en cours...");
    try {
      const project = await createProject(createName.trim(), session, onSessionRefresh);
      setProjects((prev) => [...prev, project].sort((left, right) => left.id - right.id));
      resetCreateFlow();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Impossible de créer le projet.");
    } finally {
      setActionBusy(null);
    }
  }

  async function onCreateProjectFromImport() {
    if (!session) {
      router.push("/login");
      return;
    }
    if (!createName.trim()) {
      setError("Le nom du projet est obligatoire.");
      return;
    }
    if (!createFile) {
      setError("Sélectionne un fichier MS Project XML.");
      return;
    }

    setError(null);
    setActionBusy("Import du projet en cours...");
    try {
      const project = await createProject(createName.trim(), session, onSessionRefresh);
      const batch = await createImportBatch(
        project.id,
        createName.trim(),
        session,
        onSessionRefresh,
      );
      await uploadImportSourceXml(batch.id, createFile, session, onSessionRefresh);
      await runImportBatch(batch.id, session, onSessionRefresh);

      let status = await getImportBatchStatus(batch.id, session, onSessionRefresh);
      for (let index = 0; index < 20; index += 1) {
        if (status.status === "success" || status.status === "failed") {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
        status = await getImportBatchStatus(batch.id, session, onSessionRefresh);
      }

      if (status.status !== "success") {
        throw new Error(status.errorMessage ?? "Import en échec.");
      }
      if (!status.projectId) {
        throw new Error("Import terminé sans identifiant de projet.");
      }

      await refreshProjects(session);
      resetCreateFlow();
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      if (cause instanceof ApiError) {
        setError(cause.message);
      } else if (cause instanceof Error) {
        setError(cause.message);
      } else {
        setError("Erreur inattendue pendant la création du projet.");
      }
    } finally {
      setActionBusy(null);
    }
  }

  function startRename(project: Project) {
    setEditingProjectId(project.id);
    setEditingName(project.name);
  }

  async function onSaveRename(projectId: number) {
    if (!session) {
      router.push("/login");
      return;
    }
    if (!editingName.trim()) {
      setError("Le nom du projet est obligatoire.");
      return;
    }

    setError(null);
    setActionBusy("Mise à jour du projet...");
    try {
      const updated = await updateProjectName(
        projectId,
        editingName.trim(),
        session,
        onSessionRefresh,
      );
      setProjects((prev) => prev.map((project) => (project.id === updated.id ? updated : project)));
      setEditingProjectId(null);
      setEditingName("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Impossible de modifier le projet.");
    } finally {
      setActionBusy(null);
    }
  }

  async function onDeleteProject(project: Project) {
    if (!session) {
      router.push("/login");
      return;
    }

    const confirmed = window.confirm(
      `Supprimer définitivement le projet \"${project.name}\" ? Cette action est irréversible.`,
    );
    if (!confirmed) {
      return;
    }

    setError(null);
    setActionBusy("Suppression du projet...");
    try {
      await deleteProject(project.id, session, onSessionRefresh);
      setProjects((prev) => prev.filter((item) => item.id !== project.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Impossible de supprimer le projet.");
    } finally {
      setActionBusy(null);
    }
  }

  async function onExportProject(project: Project) {
    if (!session) {
      router.push("/login");
      return;
    }

    setError(null);
    setActionBusy(`Export XML du projet ${project.id}...`);
    try {
      const blob = await exportProjectXml(project.id, session, onSessionRefresh);
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${project.name || `project-${project.id}`}.xml`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Impossible d'exporter le projet.");
    } finally {
      setActionBusy(null);
    }
  }

  function logout() {
    clearSession();
    router.push("/login");
  }

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 className="title">Gestion des projets</h1>
            <p className="subtitle">
              {me ? `Connecté en tant que ${me.email}` : "Chargement utilisateur..."}
            </p>
          </div>
          <button className="btn" onClick={logout} type="button">
            Déconnexion
          </button>
        </div>

        <div className="row" style={{ marginTop: "1rem" }}>
          {!createMode ? (
            <button className="btn btn-primary" type="button" onClick={() => setCreateMode(true)}>
              Créer projet
            </button>
          ) : null}
        </div>

        {createMode ? (
          <div className="panel" style={{ marginTop: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>Nouveau projet</h2>

            {createStep === "name" ? (
              <>
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
                <div className="row" style={{ marginTop: "0.8rem" }}>
                  <button className="btn btn-primary" type="button" onClick={() => void onCreateContinue()}>
                    Importer un fichier
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={Boolean(actionBusy)}
                    onClick={() => void onCreateManualProject()}
                  >
                    Créer sans import
                  </button>
                  <button className="btn" type="button" onClick={resetCreateFlow}>
                    Annuler
                  </button>
                </div>
              </>
            ) : null}

            {createStep === "file" ? (
              <>
                <p className="subtitle" style={{ marginTop: "0.4rem" }}>
                  Projet: <strong>{createName.trim()}</strong>
                </p>
                <div className="field">
                  <label htmlFor="project-file">Fichier MS Project (.xml)</label>
                  <input
                    id="project-file"
                    type="file"
                    accept=".xml,application/xml,text/xml"
                    onChange={(event) => {
                      const file = event.target.files?.[0] ?? null;
                      if (file && file.size > MAX_IMPORT_FILE_SIZE) {
                        setCreateFile(null);
                        setError("Le fichier XML ne doit pas dépasser 25 MiB.");
                        event.target.value = "";
                        return;
                      }
                      setError(null);
                      setCreateFile(file);
                    }}
                  />
                </div>
                <div className="row" style={{ marginTop: "0.8rem" }}>
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={!createFile || Boolean(actionBusy)}
                    onClick={() => void onCreateProjectFromImport()}
                  >
                    Importer et créer
                  </button>
                  <button className="btn" type="button" onClick={() => setCreateStep("name")}>
                    Retour
                  </button>
                  <button className="btn" type="button" onClick={resetCreateFlow}>
                    Annuler
                  </button>
                </div>
              </>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="panel">
        {busy ? <p className="muted" role="status">Chargement...</p> : null}
        {actionBusy ? <p className="muted" role="status">{actionBusy}</p> : null}
        {error ? <p className="error" role="alert">{error}</p> : null}

        {!busy && !projects.length ? <p className="muted">Aucun projet importé.</p> : null}

        {!busy && projects.length ? (
          <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">ID</th>
                <th scope="col">Nom</th>
                <th scope="col">Version source</th>
                <th scope="col">Version export</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((project) => (
                <tr key={project.id}>
                  <td>{project.id}</td>
                  <td>
                    {editingProjectId === project.id ? (
                      <input
                        type="text"
                        value={editingName}
                        onChange={(event) => setEditingName(event.target.value)}
                        maxLength={255}
                      />
                    ) : (
                      project.name
                    )}
                  </td>
                  <td>{project.source_version}</td>
                  <td>{project.save_version_out}</td>
                  <td>
                    <div className="row">
                      <Link className="btn" href={`/projects/${project.id}`}>
                        Ouvrir
                      </Link>
                      {editingProjectId === project.id ? (
                        <>
                          <button
                            className="btn"
                            type="button"
                            onClick={() => void onSaveRename(project.id)}
                          >
                            Sauver nom
                          </button>
                          <button
                            className="btn"
                            type="button"
                            onClick={() => {
                              setEditingProjectId(null);
                              setEditingName("");
                            }}
                          >
                            Annuler
                          </button>
                        </>
                      ) : (
                        <button className="btn" type="button" onClick={() => startRename(project)}>
                          Modifier
                        </button>
                      )}
                      <button className="btn" type="button" onClick={() => void onExportProject(project)}>
                        Export XML
                      </button>
                      <button
                        className="btn"
                        type="button"
                        onClick={() => void onDeleteProject(project)}
                      >
                        Supprimer
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
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
    </>
  );
}
