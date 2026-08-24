"use client";

import type { FormEventHandler } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
      <div className="flex justify-end">
        <Button type="button" onClick={() => props.onSetCreateUserMode(true)}>
          Ajouter un utilisateur
        </Button>
      </div>

      {props.usersError ? <Alert variant="destructive"><AlertDescription>{props.usersError}</AlertDescription></Alert> : null}
      <Table>
        <TableHeader><TableRow><TableHead>ID</TableHead><TableHead>Email</TableHead><TableHead>Statut</TableHead><TableHead>Rôle</TableHead><TableHead>Actions</TableHead></TableRow></TableHeader>
        <TableBody>{props.users.map((user) => <TableRow key={user.id}><TableCell>{user.id}</TableCell><TableCell>{user.email}</TableCell><TableCell><Badge variant={user.is_active ? "secondary" : "outline"}>{user.is_active ? "Actif" : "Inactif"}</Badge></TableCell><TableCell><Badge variant={user.is_admin ? "secondary" : "outline"}>{user.is_admin ? "Admin" : "Standard"}</Badge></TableCell><TableCell><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => props.onToggleStatus(user)} type="button" disabled={props.actionBusy}>{user.is_active ? "Désactiver" : "Activer"}</Button><Button variant="outline" size="sm" onClick={() => props.onToggleAdmin(user)} type="button" disabled={props.actionBusy}>{user.is_admin ? "Retirer admin" : "Promouvoir admin"}</Button><Button variant="destructive" size="sm" onClick={() => props.onRemove(user)} type="button" disabled={props.actionBusy}>Supprimer</Button></div></TableCell></TableRow>)}</TableBody>
      </Table>

      <Dialog open={props.createUserMode} onOpenChange={props.onSetCreateUserMode}>
        <DialogContent>
          <DialogHeader><DialogTitle>Nouvel utilisateur</DialogTitle><DialogDescription>Créez un accès à la console Waterfall.</DialogDescription></DialogHeader>
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