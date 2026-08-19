"use client";

import type { ResourceRole } from "@/lib/backend";

type CapacityDraft = { personCount: string; availableHours: string };

type CapacityTableProps = {
  roles: ResourceRole[];
  drafts: Record<number, CapacityDraft>;
  actionBusy: boolean;
  onDraftChange: (roleId: number, draft: CapacityDraft) => void;
  onSave: (roleId: number) => void;
};

export function CapacityTable(props: CapacityTableProps) {
  return (
    <section className="panel panel-stack">
      <h2>Capacités</h2>
      <div className="table-scroll">
        <table className="table">
          <thead><tr><th scope="col">Rôle</th><th scope="col">Nombre de personnes</th><th scope="col">Heures disponibles</th><th scope="col">Actions</th></tr></thead>
          <tbody>{props.roles.map((role) => { const draft = props.drafts[role.id] ?? { personCount: "0.00", availableHours: "0.00" }; return <tr key={role.id}><td><strong>{role.code}</strong> {role.name}</td><td><input type="number" min="0" step="0.01" value={draft.personCount} onChange={(event) => props.onDraftChange(role.id, { ...draft, personCount: event.target.value })} /></td><td><input type="number" min="0" step="0.01" value={draft.availableHours} onChange={(event) => props.onDraftChange(role.id, { ...draft, availableHours: event.target.value })} /></td><td className="table-actions"><button className="btn btn-primary" type="button" disabled={props.actionBusy} onClick={() => props.onSave(role.id)}>Enregistrer</button></td></tr>; })}</tbody>
        </table>
      </div>
    </section>
  );
}
