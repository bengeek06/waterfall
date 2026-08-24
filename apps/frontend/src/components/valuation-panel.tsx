"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { CostCategory, CostType } from "@/lib/backend";

type ValuationPanelProps = { categories: CostCategory[]; costTypes: CostType[]; inflationYear: string; inflationValue: string; currency: string; drafts: Record<string, string>; busy: boolean; onCurrencyChange: (value: string) => void; onInflationChange: (value: string) => void; onRateChange: (key: string, value: string) => void; onSave: () => void };

export function ValuationPanel(props: ValuationPanelProps) {
  const laborCategories = props.categories.filter((category) => props.costTypes.some((type) => type.id === category.cost_type_id && type.kind === "labor"));
  const years = [-4, -3, -2, -1, 0].map((offset) => new Date().getFullYear() + offset);

  return <Card className="mt-4"><CardHeader><CardTitle>Valorisation</CardTitle></CardHeader><CardContent className="grid gap-6"><div className="grid gap-4 sm:grid-cols-2"><div className="grid gap-2"><Label htmlFor="display-currency">Devise</Label><select id="display-currency" className="h-8 rounded-md border border-input bg-background px-2 text-sm" value={props.currency} onChange={(event) => props.onCurrencyChange(event.target.value)}><option value="EUR">EUR</option><option value="USD">Dollar</option></select></div><div className="grid gap-2"><Label htmlFor="inflation-value">Inflation ({props.inflationYear})</Label><div className="flex items-center gap-2"><Input id="inflation-value" type="number" min="-100" step="0.01" value={props.inflationValue} onChange={(event) => props.onInflationChange(event.target.value)} placeholder="Pourcentage" /><span className="text-sm text-muted-foreground">%</span></div></div></div><Table><TableHeader><TableRow><TableHead>Code comptable</TableHead>{years.map((year) => <TableHead key={year} className={year === years.at(-1) ? "bg-muted" : undefined}>{year}</TableHead>)}</TableRow></TableHeader><TableBody>{laborCategories.map((category) => <TableRow key={category.id}><TableCell className="font-medium">{category.accounting_code}</TableCell>{years.map((year) => { const key = `${category.id}:${year}`; return <TableCell key={year} className={year === years.at(-1) ? "bg-muted" : undefined}><Input aria-label={`${category.accounting_code} ${year}`} type="number" step="0.01" min="0" value={props.drafts[key] ?? ""} onChange={(event) => props.onRateChange(key, event.target.value)} placeholder="-" /></TableCell>; })}</TableRow>)}</TableBody></Table><div className="flex justify-end"><Button type="button" disabled={props.busy} onClick={props.onSave}>Enregistrer</Button></div></CardContent></Card>;
}
