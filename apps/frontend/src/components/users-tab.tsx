"use client";

import type { FormEventHandler } from "react";

import type { AuthUserAdmin } from "@/lib/backend";

type UsersTabProps = {
  users: AuthUserAdmin[];
  usersError: string | null;
  createUserMode: boolean;
  newEmail: string;
  newPassword: string;
  actionBusy: boolean;
  onCreateUser: FormEventHandler<HTMLFormElement>;
  onSetCreateUserMode: (enabled: boolean) => void;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onToggleStatus: (user: AuthUserAdmin) => void;
  onToggleAdmin: (user: AuthUserAdmin) => void;
  onRemove: (user: AuthUserAdmin) => void;
};

export function UsersTab(props: UsersTabProps) {
  return (
    <>
      <section className="panel">
        <div className="row" style={{ marginTop: "0" }}>
          <button className="btn btn-primary" type="button" onClick={() => props.onSetCreateUserMode(true)}>
            Ajouter un utilisateur
          </button>
        </div>
        {props.createUserMode ? (
          <form onSubmit={props.onCreateUser} style={{ marginTop: "1rem" }}>
            <div className="grid-3">
              <div className="field"><label htmlFor="new-user-email">Email</label><input id="new-user-email" type="email" value={props.newEmail} onChange={(event) => props.onEmailChange(event.target.value)} autoComplete="off" required /></div>
              <div className="field"><label htmlFor="new-user-password">Mot de passe</label><input id="new-user-password" type="password" value={props.newPassword} onChange={(event) => props.onPasswordChange(event.target.value)} minLength={8} autoComplete="new-password" required /></div>
            </div>
            <div className="row"><button className="btn btn-primary" type="submit" disabled={props.actionBusy}>{props.actionBusy ? "Création..." : "Créer"}</button><button className="btn" type="button" onClick={() => props.onSetCreateUserMode(false)}>Annuler</button></div>
          </form>
        ) : null}
      </section>

      <section className="panel">
        {props.usersError ? <p className="error" role="alert">{props.usersError}</p> : null}
        <div className="table-scroll">
          <table className="table">
            <thead><tr><th scope="col">ID</th><th scope="col">Email</th><th scope="col">Statut</th><th scope="col">Rôle</th><th scope="col">Actions</th></tr></thead>
            <tbody>{props.users.map((user) => <tr key={user.id}><td>{user.id}</td><td>{user.email}</td><td>{user.is_active ? "Actif" : "Inactif"}</td><td>{user.is_admin ? "Admin" : "Standard"}</td><td className="table-actions"><div className="row"><button className="btn" onClick={() => props.onToggleStatus(user)} type="button" disabled={props.actionBusy}>{user.is_active ? "Désactiver" : "Activer"}</button><button className="btn" onClick={() => props.onToggleAdmin(user)} type="button" disabled={props.actionBusy}>{user.is_admin ? "Retirer admin" : "Promouvoir admin"}</button><button className="btn btn-danger" onClick={() => props.onRemove(user)} type="button" disabled={props.actionBusy}>Supprimer</button></div></td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </>
  );
}