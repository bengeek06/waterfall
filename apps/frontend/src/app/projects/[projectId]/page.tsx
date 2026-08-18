"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  SessionExpiredError,
  Task,
  getProjectTasks,
  updateTaskDescription,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

const TASK_PAGE_SIZE = 200;

export default function ProjectDetailsPage() {
  const router = useRouter();
  const params = useParams<{ projectId: string }>();
  const projectId = Number(params.projectId);

  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskOffset, setTaskOffset] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [savingTaskUid, setSavingTaskUid] = useState<number | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const onSessionRefresh = useMemo(
    () => (next: SessionTokens) => {
      setSession(next);
      setSessionState(next);
    },
    [],
  );

  useEffect(() => {
    async function load() {
      if (!session || Number.isNaN(projectId)) {
        if (!session) {
          router.push("/login");
        }
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const tasksData = await getProjectTasks(
          projectId,
          session,
          onSessionRefresh,
          TASK_PAGE_SIZE,
          taskOffset,
        );
        setTasks(tasksData);
        const initialDrafts: Record<number, string> = {};
        for (const task of tasksData) {
          initialDrafts[task.uid] = task.description ?? "";
        }
        setDrafts(initialDrafts);
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
          setError("Erreur inattendue lors du chargement des tâches");
        }
      } finally {
        setBusy(false);
      }
    }

    void load();
  }, [onSessionRefresh, projectId, router, session, taskOffset]);

  async function saveDescription(task: Task) {
    if (!session) {
      return;
    }
    if (savingTaskUid === task.uid) {
      return;
    }

    const draft = (drafts[task.uid] ?? "").trim();
    const description = draft.length ? draft : null;

    setSavingTaskUid(task.uid);
    try {
      const updated = await updateTaskDescription(
        projectId,
        task.uid,
        description,
        session,
        onSessionRefresh,
      );
      setTasks((prev) => prev.map((item) => (item.uid === updated.uid ? updated : item)));
      setDrafts((prev) => ({ ...prev, [task.uid]: updated.description ?? "" }));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Sauvegarde impossible");
    } finally {
      setSavingTaskUid(null);
    }
  }

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 className="title">Projet #{projectId}</h1>
            <p className="subtitle">Edition des descriptions de tâches.</p>
          </div>
          <Link href="/projects" className="btn">
            Retour projets
          </Link>
        </div>
      </section>

      <section className="panel">
        {busy ? <p className="muted">Chargement...</p> : null}
        {error ? <p className="error">{error}</p> : null}

        {!busy && !tasks.length ? <p className="muted">Aucune tâche.</p> : null}

        {!busy && tasks.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>UID</th>
                <th>Nom</th>
                <th>Avancement</th>
                <th>Description</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.uid}>
                  <td>{task.uid}</td>
                  <td>
                    <strong>{task.name}</strong>
                    <div className="muted">{task.outline_number ?? "-"}</div>
                  </td>
                  <td>{task.percent_complete ?? 0}%</td>
                  <td style={{ minWidth: "280px" }}>
                    <textarea
                      rows={3}
                      value={drafts[task.uid] ?? ""}
                      onChange={(event) =>
                        setDrafts((prev) => ({ ...prev, [task.uid]: event.target.value }))
                      }
                    />
                  </td>
                  <td>
                    <button
                      className="btn btn-primary"
                      disabled={savingTaskUid === task.uid}
                      onClick={() => void saveDescription(task)}
                    >
                      {savingTaskUid === task.uid ? "Sauvegarde..." : "Sauver"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}

        {!busy ? (
          <div className="row" style={{ marginTop: "1rem", justifyContent: "space-between" }}>
            <span className="muted">
              {tasks.length ? `Tâches ${taskOffset + 1} à ${taskOffset + tasks.length}` : ""}
            </span>
            <div className="row">
              <button
                className="btn"
                type="button"
                disabled={taskOffset === 0}
                onClick={() => setTaskOffset((current) => Math.max(0, current - TASK_PAGE_SIZE))}
              >
                Précédent
              </button>
              <button
                className="btn"
                type="button"
                disabled={tasks.length < TASK_PAGE_SIZE}
                onClick={() => setTaskOffset((current) => current + TASK_PAGE_SIZE)}
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
