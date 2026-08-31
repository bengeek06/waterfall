"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ResourceRole } from "@/lib/backend";

type CapacityDraft = { personCount: string; availableHours: string };

type CapacityTableProps = {
  roles: ResourceRole[];
  drafts: Record<number, CapacityDraft>;
  actionBusy: boolean;
  nodeCodeById: Map<number, string>;
  onDraftChange: (roleId: number, draft: CapacityDraft) => void;
  onSave: (roleId: number) => void;
};

export function CapacityTable(props: CapacityTableProps) {
  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>Capacités</CardTitle></CardHeader>
      <CardContent>
        <Table>
          <TableHeader><TableRow><TableHead>Rôle</TableHead><TableHead>Nombre de personnes</TableHead><TableHead>Heures disponibles</TableHead><TableHead>Actions</TableHead></TableRow></TableHeader>
          <TableBody>{props.roles.map((role) => { const draft = props.drafts[role.id] ?? { personCount: "0.00", availableHours: "0.00" }; const nodeCode = props.nodeCodeById.get(role.node_id) ?? "?"; return <TableRow key={role.id}><TableCell>{role.name} — {nodeCode}</TableCell><TableCell><Input type="number" min="0" step="0.01" value={draft.personCount} onChange={(event) => props.onDraftChange(role.id, { ...draft, personCount: event.target.value })} /></TableCell><TableCell><Input type="number" min="0" step="0.01" value={draft.availableHours} onChange={(event) => props.onDraftChange(role.id, { ...draft, availableHours: event.target.value })} /></TableCell><TableCell><Button size="sm" type="button" disabled={props.actionBusy} onClick={() => props.onSave(role.id)}>Enregistrer</Button></TableCell></TableRow>; })}</TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
