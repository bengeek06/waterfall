"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Calendar, ResourceRole } from "@/lib/backend";

type RoleCalendarsTableProps = {
  roles: ResourceRole[];
  calendars: Calendar[];
  drafts: Record<number, string>;
  actionBusy: boolean;
  nodeCodeById: Map<number, string>;
  onDraftChange: (roleId: number, calendarId: string) => void;
  onSave: (roleId: number) => void;
};

export function RoleCalendarsTable(props: RoleCalendarsTableProps) {
  const activeCalendars = props.calendars.filter((calendar) => calendar.is_active);

  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>Calendriers des rôles</CardTitle></CardHeader>
      <CardContent>
        <Table>
          <TableHeader><TableRow><TableHead>Rôle</TableHead><TableHead>Calendrier</TableHead><TableHead>Actions</TableHead></TableRow></TableHeader>
          <TableBody>
            {props.roles.map((role) => {
              const draft = props.drafts[role.id] ?? (role.calendar_id ? String(role.calendar_id) : "");
              const assignedInactiveCalendar = role.calendar_id != null && !activeCalendars.some((calendar) => calendar.id === role.calendar_id)
                ? props.calendars.find((calendar) => calendar.id === role.calendar_id)
                : undefined;
              const nodeCode = props.nodeCodeById.get(role.node_id) ?? "?";
              return (
                <TableRow key={role.id}>
                  <TableCell>{role.name} — {nodeCode}</TableCell>
                  <TableCell>
                    <select
                      aria-label={`Calendrier de ${role.name} — ${nodeCode}`}
                      className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                      value={draft}
                      disabled={props.actionBusy}
                      onChange={(event) => props.onDraftChange(role.id, event.target.value)}
                    >
                      <option value="">Calendrier par défaut</option>
                      {assignedInactiveCalendar ? (
                        <option value={assignedInactiveCalendar.id}>{assignedInactiveCalendar.code} - {assignedInactiveCalendar.name} (inactif)</option>
                      ) : null}
                      {activeCalendars.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.code} - {calendar.name}</option>)}
                    </select>
                  </TableCell>
                  <TableCell><Button size="sm" type="button" disabled={props.actionBusy} onClick={() => props.onSave(role.id)}>Enregistrer</Button></TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
