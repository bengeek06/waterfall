"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";

import {
  ApiError,
  AuthUserAdmin,
  SessionExpiredError,
  createUser,
  deleteUser,
  getMe,
  getUsers,
  restoreSession,
  setUserRole,
  setUserStatus,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

export default function UsersPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [users, setUsers] = useState<AuthUserAdmin[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [createMode, setCreateMode] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");

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
        try {
          const restoredSession = await restoreSession();
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
        const usersData = await getUsers(session, onSessionRefresh);
        setUsers(usersData);
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
    const nextStatus = !user.is_active;
    const action = nextStatus ? "activer" : "désactiver";
    if (!window.confirm(`${action[0].toUpperCase()}${action.slice(1)} le compte ${user.email} ?`)) {
      return;
    }
    setActionBusy(true);
    try {
      const updated = await setUserStatus(user.id, nextStatus, session, onSessionRefresh);
      setUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de modifier le statut");
    } finally {
      setActionBusy(false);
    }
  }

  async function toggleAdmin(user: AuthUserAdmin) {
    if (!session) {
      return;
    }
    const nextAdmin = !user.is_admin;
    const action = nextAdmin ? "promouvoir administrateur" : "retirer les droits administrateur";
    if (!window.confirm(`${action[0].toUpperCase()}${action.slice(1)} pour ${user.email} ?`)) {
      return;
    }
    setActionBusy(true);
    try {
      const updated = await setUserRole(user.id, nextAdmin, session, onSessionRefresh);
      setUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de modifier le role");
    } finally {
      setActionBusy(false);
    }
  }

  async function addUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      router.push("/login");
      return;
    }

    setError(null);
    setActionBusy(true);
    try {
      const created = await createUser(newEmail, newPassword, session, onSessionRefresh);
      setUsers((prev) => [...prev, created].sort((left, right) => left.id - right.id));
      setNewEmail("");
      setNewPassword("");
      setCreateMode(false);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de créer l'utilisateur");
    } finally {
      setActionBusy(false);
    }
  }

  async function removeUser(user: AuthUserAdmin) {
    if (!session) {
      router.push("/login");
      return;
    }
    if (!window.confirm(`Supprimer définitivement ${user.email} ?`)) {
      return;
    }

    setError(null);
    setActionBusy(true);
    try {
      await deleteUser(user.id, session, onSessionRefresh);
      setUsers((prev) => prev.filter((item) => item.id !== user.id));
    } catch (cause) {
      if (cause instanceof SessionExpiredError) {
        clearSession();
        router.push("/login");
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "Impossible de supprimer l'utilisateur");
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <>
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 className="title">Gestion des utilisateurs</h1>
          </div>
        </div>
        <div className="row" style={{ marginTop: "1rem" }}>
          <button className="btn btn-primary" type="button" onClick={() => setCreateMode(true)}>
            Ajouter un utilisateur
          </button>
        </div>
        {createMode ? (
          <form onSubmit={addUser} style={{ marginTop: "1rem" }}>
            <div className="grid-3">
              <div className="field">
                <label htmlFor="new-user-email">Email</label>
                <input
                  id="new-user-email"
                  type="email"
                  value={newEmail}
                  onChange={(event) => setNewEmail(event.target.value)}
                  autoComplete="off"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="new-user-password">Mot de passe</label>
                <input
                  id="new-user-password"
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  minLength={8}
                  autoComplete="new-password"
                  required
                />
              </div>
            </div>
            <div className="row">
              <button className="btn btn-primary" type="submit" disabled={actionBusy}>
                {actionBusy ? "Création..." : "Créer"}
              </button>
              <button className="btn" type="button" onClick={() => setCreateMode(false)}>
                Annuler
              </button>
            </div>
          </form>
        ) : null}
      </section>

      <section className="panel">
        {busy ? <p className="muted" role="status">Chargement...</p> : null}
        {error ? <p className="error" role="alert">{error}</p> : null}

        {!busy ? (
          <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">ID</th>
                <th scope="col">Email</th>
                <th scope="col">Statut</th>
                <th scope="col">Role</th>
                <th scope="col">Actions</th>
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
                      <button className="btn" onClick={() => void toggleStatus(user)} type="button" disabled={actionBusy}>
                        {user.is_active ? "Désactiver" : "Activer"}
                      </button>
                      <button className="btn" onClick={() => void toggleAdmin(user)} type="button" disabled={actionBusy}>
                        {user.is_admin ? "Retirer admin" : "Promouvoir admin"}
                      </button>
                      <button
                        className="btn btn-danger"
                        onClick={() => void removeUser(user)}
                        type="button"
                        disabled={actionBusy}
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
      </section>
    </>
  );
}
