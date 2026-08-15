"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  ApiError,
  AuthUser,
  AuthUserAdmin,
  getMe,
  getUsers,
  setUserRole,
  setUserStatus,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

export default function UsersPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [me, setMe] = useState<AuthUser | null>(null);
  const [users, setUsers] = useState<AuthUserAdmin[]>([]);
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
        const usersData = await getUsers(session, onSessionRefresh);
        setUsers(usersData);
      } catch (cause) {
        if (cause instanceof ApiError) {
          if (cause.status === 401) {
            clearSession();
            router.push("/login");
            return;
          }
          setError(cause.message);
        } else {
          setError("Erreur inattendue lors du chargement des utilisateurs");
        }
      } finally {
        setBusy(false);
      }
    }

    void load();
  }, [onSessionRefresh, router, session]);

  async function toggleStatus(user: AuthUserAdmin) {
    if (!session) {
      return;
    }
    try {
      const updated = await setUserStatus(user.id, !user.is_active, session, onSessionRefresh);
      setUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Impossible de modifier le statut");
    }
  }

  async function toggleAdmin(user: AuthUserAdmin) {
    if (!session) {
      return;
    }
    try {
      const updated = await setUserRole(user.id, !user.is_admin, session, onSessionRefresh);
      setUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Impossible de modifier le role");
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
            <h1 className="title">Gestion des utilisateurs</h1>
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

        {!busy ? (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Email</th>
                <th>Statut</th>
                <th>Role</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.id}</td>
                  <td>{user.email}</td>
                  <td>{user.is_active ? "Actif" : "Inactif"}</td>
                  <td>{user.is_admin ? "Admin" : "Standard"}</td>
                  <td>
                    <div className="row">
                      <button className="btn" onClick={() => void toggleStatus(user)} type="button">
                        {user.is_active ? "Désactiver" : "Activer"}
                      </button>
                      <button className="btn" onClick={() => void toggleAdmin(user)} type="button">
                        {user.is_admin ? "Retirer admin" : "Promouvoir admin"}
                      </button>
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
