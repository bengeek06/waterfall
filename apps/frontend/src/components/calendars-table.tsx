"use client";

import type { FormEventHandler } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Calendar } from "@/lib/backend";

export type WeekdayDraft = { day_type: number; hours_per_day: string };

export const WEEKDAY_ORDER: { dayType: number; label: string }[] = [
  { dayType: 2, label: "Lun" },
  { dayType: 3, label: "Mar" },
  { dayType: 4, label: "Mer" },
  { dayType: 5, label: "Jeu" },
  { dayType: 6, label: "Ven" },
  { dayType: 7, label: "Sam" },
  { dayType: 1, label: "Dim" },
];

export function defaultWeekdays(): WeekdayDraft[] {
  return WEEKDAY_ORDER.map(({ dayType }) => ({
    day_type: dayType,
    hours_per_day: dayType >= 2 && dayType <= 6 ? "7.00" : "0.00",
  }));
}

export type CalendarDraft = { code: string; name: string; weeksPerYear: string; weekdays: WeekdayDraft[] };

export type CalendarsTableProps = {
  items: Calendar[];
  code: string;
  name: string;
  weeksPerYear: string;
  weekdays: WeekdayDraft[];
  draft: CalendarDraft;
  editingId: number | null;
  busy: boolean;
  calendarIdsInUseByActiveRoles: Set<number>;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onCodeChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onWeeksPerYearChange: (value: string) => void;
  onWeekdayChange: (dayType: number, value: string) => void;
  onStartEdit: (item: Calendar) => void;
  onDraftChange: (field: "code" | "name" | "weeksPerYear", value: string) => void;
  onDraftWeekdayChange: (dayType: number, value: string) => void;
  onSave: (item: Calendar) => void;
  onCancel: () => void;
  onToggle: (item: Calendar) => void;
};

export function CalendarsTable(props: CalendarsTableProps) {
  return (
    <Card className="mt-4">
      <CardHeader><CardTitle>Calendriers de travail</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={props.onSubmit}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Nom</TableHead>
                <TableHead>Semaines/an</TableHead>
                {WEEKDAY_ORDER.map(({ label }) => <TableHead key={label}>{label}</TableHead>)}
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell><Input aria-label="Code du nouveau calendrier" value={props.code} onChange={(event) => props.onCodeChange(event.target.value)} required /></TableCell>
                <TableCell><Input aria-label="Nom du nouveau calendrier" value={props.name} onChange={(event) => props.onNameChange(event.target.value)} required /></TableCell>
                <TableCell><Input aria-label="Semaines par an du nouveau calendrier" type="number" min="1" max="53" value={props.weeksPerYear} onChange={(event) => props.onWeeksPerYearChange(event.target.value)} required /></TableCell>
                {WEEKDAY_ORDER.map(({ dayType, label }) => {
                  const value = props.weekdays.find((weekday) => weekday.day_type === dayType)?.hours_per_day ?? "0.00";
                  return (
                    <TableCell key={dayType}>
                      <Input
                        aria-label={`Heures du ${label} pour le nouveau calendrier`}
                        type="number"
                        min="0"
                        max="24"
                        step="0.25"
                        className="w-16"
                        value={value}
                        onChange={(event) => props.onWeekdayChange(dayType, event.target.value)}
                      />
                    </TableCell>
                  );
                })}
                <TableCell><Button size="sm" disabled={props.busy} type="submit">Ajouter</Button></TableCell>
              </TableRow>
              {props.items.map((item) => {
                const editing = props.editingId === item.id;
                const inUseByActiveRole = item.is_active && props.calendarIdsInUseByActiveRoles.has(item.id);
                return (
                  <TableRow key={item.id} className={item.is_active ? undefined : "opacity-55"}>
                    <TableCell>{editing ? <Input aria-label={`Code de ${item.code}`} value={props.draft.code} onChange={(event) => props.onDraftChange("code", event.target.value)} /> : <span className="font-medium flex items-center gap-2">{item.code}{item.is_default ? <Badge variant="secondary">Par défaut</Badge> : null}</span>}</TableCell>
                    <TableCell>{editing ? <Input aria-label={`Nom de ${item.code}`} value={props.draft.name} onChange={(event) => props.onDraftChange("name", event.target.value)} /> : item.name}</TableCell>
                    <TableCell>{editing ? <Input aria-label={`Semaines par an de ${item.code}`} type="number" min="1" max="53" value={props.draft.weeksPerYear} onChange={(event) => props.onDraftChange("weeksPerYear", event.target.value)} /> : item.weeks_per_year}</TableCell>
                    {WEEKDAY_ORDER.map(({ dayType, label }) => {
                      if (editing) {
                        const value = props.draft.weekdays.find((weekday) => weekday.day_type === dayType)?.hours_per_day ?? "0.00";
                        return (
                          <TableCell key={dayType}>
                            <Input
                              aria-label={`Heures du ${label} de ${item.code}`}
                              type="number"
                              min="0"
                              max="24"
                              step="0.25"
                              className="w-16"
                              value={value}
                              onChange={(event) => props.onDraftWeekdayChange(dayType, event.target.value)}
                            />
                          </TableCell>
                        );
                      }
                      const hours = (item.weekdays ?? []).find((weekday) => weekday.day_type === dayType)?.hours_per_day ?? "0";
                      return <TableCell key={dayType}>{hours}</TableCell>;
                    })}
                    <TableCell>
                      <div className="flex gap-2">
                        {editing ? (
                          <>
                            <Button size="sm" type="button" disabled={props.busy} onClick={() => props.onSave(item)}>Enregistrer</Button>
                            <Button size="sm" variant="outline" type="button" onClick={props.onCancel}>Annuler</Button>
                          </>
                        ) : (
                          <Button size="sm" variant="outline" type="button" onClick={() => props.onStartEdit(item)}>Modifier</Button>
                        )}
                        <Button size="sm" variant="outline" type="button" disabled={props.busy || inUseByActiveRole || (item.is_active && item.is_default)} onClick={() => props.onToggle(item)}>{item.is_active ? "Désactiver" : "Réactiver"}</Button>
                        {inUseByActiveRole ? <span className="text-xs text-muted-foreground">Assigné à un rôle actif</span> : null}
                        {item.is_default ? <span className="text-xs text-muted-foreground">{item.is_active ? "Calendrier par défaut" : "Calendrier par défaut (inactif)"}</span> : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </form>
      </CardContent>
    </Card>
  );
}
