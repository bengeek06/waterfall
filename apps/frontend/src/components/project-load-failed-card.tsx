"use client";

import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export type ProjectLoadFailedCardProps = {
  projectId: number;
  error: string | null;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the early-return card/alert shown when the
// initial project load failed. Verbatim JSX move -- see page.tsx call site for wiring.
export function ProjectLoadFailedCard({ projectId, error }: ProjectLoadFailedCardProps) {
  return (
    <>
      <Card>
        <CardContent className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold">Projet #{projectId}</h1>
            </div>
            <p className="mt-1 text-sm text-muted-foreground italic">
              Le projet est indisponible tant que son chargement initial échoue.
            </p>
          </div>
          <Button variant="outline" nativeButton={false} render={<Link href="/projects" />}>Retour projets</Button>
        </CardContent>
      </Card>

      <Alert className="mt-4" variant="destructive">
        <AlertTitle>Projet indisponible</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    </>
  );
}
