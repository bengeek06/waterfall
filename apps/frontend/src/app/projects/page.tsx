"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, AuthUser, Project, getMe, getProjects } from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

export default function ProjectsPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [me, setMe] = useState<AuthUser | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
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
      if (!session) {
        router.push("/login");
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const meData = await getMe(session, onSessionRefresh);
        setMe(meData);
        const projectsData = await getProjects(session, onSessionRefresh);
        setProjects(projectsData);
      } catch (cause) {
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
  }, [onSessionRefresh, router, session]);

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
      </section>

      <section className="panel">
        {busy ? <p className="muted">Chargement...</p> : null}
        {error ? <p className="error">{error}</p> : null}

        {!busy && !projects.length ? <p className="muted">Aucun projet importé.</p> : null}

        {!busy && projects.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Nom</th>
                <th>Version source</th>
                <th>Version export</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((project) => (
                <tr key={project.id}>
                  <td>{project.id}</td>
                  <td>{project.name}</td>
                  <td>{project.source_version}</td>
                  <td>{project.save_version_out}</td>
                  <td>
                    <div className="row">
                      <Link className="btn" href={`/projects/${project.id}`}>
                        Ouvrir
                      </Link>
                      <a
                        className="btn"
                        href={`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/projects/${project.id}/export.xml`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Export XML
                      </a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
    </>
  );
}
