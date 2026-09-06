"use client";

import type { FormEventHandler } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTablePaginationState } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AuthUserAdmin } from "@/lib/backend";

export type UsersTabProps = {
  items: AuthUserAdmin[];
  pagination: DataTablePaginationState;
  onPaginationChange: (next: { offset: number; limit: number }) => void;
  sort: string | null;
  onSortChange: (next: string | null) => void;
  search: string;
  onSearchChange: (next: string) => void;
  isLoading: boolean;
  // True while a destructive-action confirmation (activate/deactivate, grant/revoke
  // admin, delete) is open for a specific user. Freezes the DataTable's own
  // search/pagination controls so the row a confirmation was opened for can't be
  // paged or filtered out from under it -- defense in depth on top of the page-level
  // fix (the confirmation always carries the exact user object it was opened with,
  // never re-derives "the user at this row" from current data).
  isActionPending: boolean;
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
  const columns: ColumnDef<AuthUserAdmin>[] = [
    {
      accessorKey: "id",
      header: "ID",
      cell: ({ row }) => row.original.id,
    },
    {
      accessorKey: "email",
      header: "Email",
      meta: { sortColumn: "email" },
    },
    {
      id: "status",
      header: "Statut",
      meta: { sortColumn: "is_active" },
      cell: ({ row }) => (
        <Badge variant={row.original.is_active ? "secondary" : "outline"}>
          {row.original.is_active ? "Actif" : "Inactif"}
        </Badge>
      ),
    },
    {
      id: "role",
      header: "Rôle",
      cell: ({ row }) => (
        <Badge variant={row.original.is_admin ? "secondary" : "outline"}>
          {row.original.is_admin ? "Admin" : "Standard"}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => {
        const user = row.original;
        return (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              type="button"
              onClick={() => props.onToggleStatus(user)}
              disabled={props.actionBusy || props.isActionPending}
            >
              {user.is_active ? "Désactiver" : "Activer"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              type="button"
              onClick={() => props.onToggleAdmin(user)}
              disabled={props.actionBusy || props.isActionPending}
            >
              {user.is_admin ? "Retirer admin" : "Promouvoir admin"}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              type="button"
              onClick={() => props.onRemove(user)}
              disabled={props.actionBusy || props.isActionPending}
            >
              Supprimer
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <>
      <div className="flex justify-end">
        <Button type="button" onClick={() => props.onSetCreateUserMode(true)}>
          Ajouter un utilisateur
        </Button>
      </div>

      {props.usersError && !props.createUserMode ? (
        <Alert variant="destructive">
          <AlertDescription>{props.usersError}</AlertDescription>
        </Alert>
      ) : null}

      <DataTable
        columns={columns}
        data={props.items}
        getRowId={(user) => String(user.id)}
        pagination={props.pagination}
        onPaginationChange={props.onPaginationChange}
        sort={props.sort}
        onSortChange={props.onSortChange}
        search={{ value: props.search, onChange: props.onSearchChange, placeholder: "Rechercher un utilisateur" }}
        isEditing={props.isActionPending}
        editingReason="Confirmez ou annulez l'action en cours pour changer de page ou filtrer."
        isLoading={props.isLoading}
      />

      <Dialog open={props.createUserMode} onOpenChange={props.onSetCreateUserMode}>
        <DialogContent>
          <DialogHeader><DialogTitle>Nouvel utilisateur</DialogTitle><DialogDescription>Créez un accès à la console Waterfall.</DialogDescription></DialogHeader>
          {props.usersError ? <Alert variant="destructive"><AlertDescription>{props.usersError}</AlertDescription></Alert> : null}
          <form onSubmit={props.onCreateUser} className="grid gap-4">
            <div className="grid gap-2"><Label htmlFor="new-user-email">Email</Label><Input id="new-user-email" type="email" value={props.newEmail} onChange={(event) => props.onEmailChange(event.target.value)} autoComplete="off" required /></div>
            <div className="grid gap-2"><Label htmlFor="new-user-password">Mot de passe</Label><Input id="new-user-password" type="password" value={props.newPassword} onChange={(event) => props.onPasswordChange(event.target.value)} minLength={8} autoComplete="new-password" required /></div>
            <DialogFooter><Button type="button" variant="outline" onClick={() => props.onSetCreateUserMode(false)}>Annuler</Button><Button type="submit" disabled={props.actionBusy}>{props.actionBusy ? "Création..." : "Créer"}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
