"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ProjectsTable } from "@/components/projects-table";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  Project,
  SessionExpiredError,
  createProject,
  deleteProject,
  getMe,
  getProjects,
  restoreSession,
} from "@/lib/backend";
import { clearSession, getSession, setSession, type SessionTokens } from "@/lib/session";

const PROJECT_PAGE_SIZE = 50;

export default function ProjectsPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectOffset, setProjectOffset] = useState(0);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [createMode, setCreateMode] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createCode, setCreateCode] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const onSessionRefresh = useMemo(
    () => (next: SessionTokens) => {
      setSession(next);
      setSessionState(next);
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!session) {
        try {
          const restoredSession = await restoreSession();
          if (cancelled) {
            return;
          }
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
        const projectsData = await getProjects(
          session,
          onSessionRefresh,
          PROJECT_PAGE_SIZE,
          projectOffset,
          includeArchived,
        );
        if (cancelled) {
          return;
        }
        setProjects(projectsData);
        setSelectedIds(new Set());
      } catch (cause) {
        if (cancelled) {
          return;
        }
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
          setError("Erreur inattendue lors du chargement des projets");
        }
      } finally {
        if (!cancelled) {
          setBusy(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [includeArchived, onSessionRefresh, projectOffset, router, session]);

  function toggleIncludeArchived() {
    setIncludeArchived((current) => !current);
    setProjectOffset(0);
    setSelectedIds(new Set());
  }

  function resetCreateFlow() {
    setCreateMode(false);
    setCreateName("");
    setCreateCode("");
    setCreateDescription("");
    setCreateError(null);
  }

  async function onCreateProject() {
    if (!session) {
      router.push("/login");
      return;
    }
    if (!createName.trim() || !createCode.trim()) {
      setCreateError("Le nom et le code du projet sont obligatoires.");
      return;
    }

    setCreateError(null);
    setActionBusy("Création du projet en cours...");
    try {
      const project = await createProject(
        {
          name: createName.trim(),
          code: createCode.trim(),
          short_description: createDescription.trim() || null,
        },
        session,
        onSessionRefresh,
      );
      setProjects((prev) => [...prev, project].sort((left, right) => left.id - right.id));
      resetCreateFlow();
    } catch (cause) {
      setCreateError(cause instanceof ApiError ? cause.message : "Impossible de créer le projet.");
    } finally {
      setActionBusy(null);
    }
  }

  async function onDeleteSelected() {
    if (!session || selectedIds.size === 0) {
      return;
    }

    const projectIds = [...selectedIds];
    setActionBusy("Suppression des projets sélectionnés...");
    try {
      for (const projectId of projectIds) {
        await deleteProject(projectId, session, onSessionRefresh);
      }
      setProjects((prev) => prev.filter((project) => !projectIds.includes(project.id)));
      setSelectedIds(new Set());
      toast.success(`${projectIds.length} projet(s) supprimé(s).`);
    } catch (cause) {
      toast.error(cause instanceof ApiError ? cause.message : "Impossible de supprimer les projets.");
    } finally {
      setActionBusy(null);
    }
  }

  return (
    <>
      <Card>
        <CardContent>
        <div className="flex flex-wrap justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Gestion des projets</h1>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button type="button" onClick={() => setCreateMode(true)}>
            Créer projet
          </Button>
        </div>

        </CardContent>
      </Card>

      <Dialog
        open={createMode}
        onOpenChange={(open) => {
          if (open) {
            setCreateMode(true);
          } else {
            resetCreateFlow();
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nouveau projet</DialogTitle>
            <DialogDescription>Créez le référentiel initial du projet.</DialogDescription>
          </DialogHeader>
          {createError ? <Alert variant="destructive"><AlertDescription>{createError}</AlertDescription></Alert> : null}
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="project-name">Nom du projet</Label>
              <Input
                id="project-name"
                value={createName}
                onChange={(event) => setCreateName(event.target.value)}
                placeholder="Ex. Projet pilote"
                maxLength={255}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="project-code">Code projet</Label>
              <Input
                id="project-code"
                value={createCode}
                onChange={(event) => setCreateCode(event.target.value)}
                placeholder="Ex. PRJ-001"
                maxLength={64}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="project-description">Description (facultatif)</Label>
              <Textarea
                id="project-description"
                rows={3}
                value={createDescription}
                onChange={(event) => setCreateDescription(event.target.value)}
                maxLength={500}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={resetCreateFlow}>
              Annuler
            </Button>
            <Button type="button" disabled={Boolean(actionBusy)} onClick={() => void onCreateProject()}>
              {actionBusy ? "Création..." : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Card className="mt-4">
        <CardContent className="pt-6">
        <label className="mb-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Checkbox
            checked={includeArchived}
            onCheckedChange={toggleIncludeArchived}
          />
          Inclure les projets perdus, terminés ou abandonnés
        </label>

        {busy ? <p className="text-sm text-muted-foreground" role="status">Chargement...</p> : null}
        {actionBusy ? <p className="text-sm text-muted-foreground" role="status">{actionBusy}</p> : null}
        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}

        {!busy && !projects.length ? <p className="text-sm text-muted-foreground">Aucun projet importé.</p> : null}

        {!busy && projects.length ? (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">
                {selectedIds.size ? `${selectedIds.size} sélectionné(s)` : ""}
              </span>
              <Button
                variant="destructive"
                type="button"
                disabled={!selectedIds.size || Boolean(actionBusy)}
                onClick={() => setDeleteDialogOpen(true)}
              >
                Supprimer la sélection
              </Button>
            </div>
            <ProjectsTable
              projects={projects}
              selectedIds={selectedIds}
              onSelectedIdsChange={setSelectedIds}
              onProjectOpen={(projectId) => router.push(`/projects/${projectId}`)}
            />
          </>
        ) : null}

        {!busy ? (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <span className="text-sm text-muted-foreground">
              {projects.length ? `Projets ${projectOffset + 1} à ${projectOffset + projects.length}` : ""}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                type="button"
                disabled={projectOffset === 0}
                onClick={() => setProjectOffset((current) => Math.max(0, current - PROJECT_PAGE_SIZE))}
              >
                Précédent
              </Button>
              <Button
                variant="outline"
                type="button"
                disabled={projects.length < PROJECT_PAGE_SIZE}
                onClick={() => setProjectOffset((current) => current + PROJECT_PAGE_SIZE)}
              >
                Suivant
              </Button>
            </div>
          </div>
        ) : null}
        </CardContent>
      </Card>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Supprimer les projets sélectionnés ?</AlertDialogTitle>
            <AlertDialogDescription>
              {selectedIds.size} projet(s) seront supprimé(s) définitivement. Cette action est irréversible.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                setDeleteDialogOpen(false);
                void onDeleteSelected();
              }}
            >
              Supprimer
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
