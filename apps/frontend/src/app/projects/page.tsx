"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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

export default function ProjectsPage() {
  const router = useRouter();
  const [session, setSessionState] = useState<SessionTokens | null>(() => getSession());
  // The table's own server-paginated/sorted/searched view (EPIC E8's DataTable
  // migration, #128, the last of the 9 tables). Unlike the multi-table
  // `resources/page.tsx`, this page has a single data source, so there is no
  // separate unfiltered "reference" list to keep alongside it -- `projectsPage`
  // is the only representation of the project list.
  const [projectsPage, setProjectsPage] = useState<{ items: Project[]; total: number }>({ items: [], total: 0 });
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsOffset, setProjectsOffset] = useState(0);
  const [projectsLimit] = useState(20);
  const [projectsSort, setProjectsSort] = useState<string | null>(null);
  const [projectsQuery, setProjectsQuery] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
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

  // Guards a reload triggered by a mutation (see `reloadProjectsPage` below)
  // against racing an in-flight pagination/sort/search/filter fetch from the
  // effect below, and vice versa -- whichever request resolves last for this
  // generation wins, matching `reloadCostTypesPage`'s own rationale in
  // `resources/page.tsx`.
  const projectsGenerationRef = useRef(0);
  // Mirrors `projectsOffset`/`projectsSort`/`projectsQuery`/`includeArchived`
  // synchronously (updated at every write site below, not via a `useEffect`) so
  // `reloadProjectsPage` -- called from `onCreateProject`/`onDeleteSelected`
  // after an `await` -- reads the *live* pagination/sort/search/filter state
  // instead of the value closed over when the mutation started. Otherwise: a
  // create/delete's own request is still in flight (the confirmation dialog
  // closes immediately, well before the mutation's own request resolves) while
  // the user pages/sorts/searches/toggles "Inclure les projets...", the
  // mutation then resolves, and the reload it triggers would silently refetch
  // and display stale data under the new controls' label -- even though, by
  // generation-counter order, that reload's response is the most recent one to
  // arrive. Same bug class and fix as `reloadUsersPage` in `resources/page.tsx`.
  const projectsOffsetRef = useRef(projectsOffset);
  const projectsSortRef = useRef(projectsSort);
  const projectsQueryRef = useRef(projectsQuery);
  const includeArchivedRef = useRef(includeArchived);

  useEffect(() => {
    const generation = ++projectsGenerationRef.current;
    const isCurrentGeneration = () => projectsGenerationRef.current === generation;

    async function load() {
      if (!session) {
        try {
          const restoredSession = await restoreSession();
          if (!isCurrentGeneration()) return;
          setSession(restoredSession);
          setSessionState(restoredSession);
        } catch {
          if (!isCurrentGeneration()) return;
          clearSession();
          router.push("/login");
        }
        return;
      }
      setProjectsLoading(true);
      setError(null);
      try {
        await getMe(session, onSessionRefresh);
        const page = await getProjects(session, onSessionRefresh, includeArchived, {
          limit: projectsLimit,
          offset: projectsOffset,
          sort: projectsSort,
          q: projectsQuery || undefined,
        });
        if (!isCurrentGeneration()) return;
        setProjectsPage(page);
        setSelectedIds(new Set());
      } catch (cause) {
        if (!isCurrentGeneration()) return;
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
        if (isCurrentGeneration()) setProjectsLoading(false);
      }
    }

    void load();
  }, [session, onSessionRefresh, router, includeArchived, projectsLimit, projectsOffset, projectsSort, projectsQuery]);

  // Reloads the table's current page in place after a create/delete mutation,
  // rather than patching `projectsPage.items` locally: server-side sort/search/
  // pagination mean the mutated row's position (or continued presence on this
  // page at all) can't be derived client-side. Mirrors `reloadCostTypesPage` in
  // `resources/page.tsx`.
  async function reloadProjectsPage() {
    if (!session) return;
    const generation = ++projectsGenerationRef.current;
    setProjectsLoading(true);
    try {
      const page = await getProjects(session, onSessionRefresh, includeArchivedRef.current, {
        limit: projectsLimit,
        offset: projectsOffsetRef.current,
        sort: projectsSortRef.current,
        q: projectsQueryRef.current || undefined,
      });
      if (projectsGenerationRef.current !== generation) return;
      // A delete can leave the current offset past the end of the list -- e.g.
      // deleting the last project on page 2 drops the total to 20 while still
      // viewing offset 20. Clamp to the last valid page and refetch once more
      // instead of rendering an empty "Aucune donnée" table while data still
      // exists on an earlier page. Mirrors `reloadUsersPage` in
      // `resources/page.tsx`.
      if (projectsOffsetRef.current > 0 && page.total <= projectsOffsetRef.current) {
        const clampedOffset = Math.max(0, Math.floor((page.total - 1) / projectsLimit) * projectsLimit);
        projectsOffsetRef.current = clampedOffset;
        setProjectsOffset(clampedOffset);
        await reloadProjectsPage();
        return;
      }
      setProjectsPage(page);
    } catch (cause) {
      if (projectsGenerationRef.current !== generation) return;
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
      }
    } finally {
      if (projectsGenerationRef.current === generation) setProjectsLoading(false);
    }
  }

  function toggleIncludeArchived() {
    setIncludeArchived((current) => {
      const next = !current;
      includeArchivedRef.current = next;
      return next;
    });
    projectsOffsetRef.current = 0;
    setProjectsOffset(0);
    setSelectedIds(new Set());
  }

  function onProjectsSortChange(nextSort: string | null) {
    projectsSortRef.current = nextSort;
    setProjectsSort(nextSort);
    projectsOffsetRef.current = 0;
    setProjectsOffset(0);
    setSelectedIds(new Set());
  }

  function onProjectsSearchChange(nextQuery: string) {
    projectsQueryRef.current = nextQuery;
    setProjectsQuery(nextQuery);
    projectsOffsetRef.current = 0;
    setProjectsOffset(0);
    setSelectedIds(new Set());
  }

  function onProjectsPaginationChange(next: { offset: number; limit: number }) {
    projectsOffsetRef.current = next.offset;
    setProjectsOffset(next.offset);
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
      await createProject(
        {
          name: createName.trim(),
          code: createCode.trim(),
          short_description: createDescription.trim() || null,
        },
        session,
        onSessionRefresh,
      );
      resetCreateFlow();
      await reloadProjectsPage();
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        clearSession();
        router.push("/login");
        return;
      }
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
    let sessionExpired = false;
    try {
      for (const projectId of projectIds) {
        await deleteProject(projectId, session, onSessionRefresh);
      }
      toast.success(`${projectIds.length} projet(s) supprimé(s).`);
    } catch (cause) {
      if (cause instanceof SessionExpiredError || (cause instanceof ApiError && cause.status === 401)) {
        sessionExpired = true;
        clearSession();
        router.push("/login");
        return;
      }
      // A failure partway through the loop still leaves the earlier ids deleted
      // server-side -- `selectedIds`/the table's current page must not keep
      // referencing them as if nothing happened. `reloadProjectsPage()` below
      // (in `finally`, so it runs on every non-session-expiry outcome) resynchronizes
      // on the real server state whether the loop fully succeeded, partially
      // succeeded, or failed on the very first id.
      toast.error(cause instanceof ApiError ? cause.message : "Impossible de supprimer les projets.");
    } finally {
      if (!sessionExpired) {
        setSelectedIds(new Set());
        await reloadProjectsPage();
      }
      setActionBusy(null);
    }
  }

  // The "select all" checkbox in ProjectsTable only ever covers the rows on the
  // current server page (see that component's own comment) -- when more than one
  // page exists, "N sélectionné(s)" alone would be ambiguous about whether the
  // selection covers just this page or the whole filtered dataset. Appending
  // "sur cette page" whenever a second page exists removes that ambiguity; with
  // a single page, "sur cette page" and "au total" mean the same thing, so the
  // plain count is left alone.
  const hasMultiplePages = projectsPage.total > projectsPage.items.length;
  const selectionLabel = selectedIds.size
    ? `${selectedIds.size} sélectionné(s)${hasMultiplePages ? " sur cette page" : ""}`
    : "";

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

        {actionBusy ? <p className="text-sm text-muted-foreground" role="status">{actionBusy}</p> : null}
        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}

        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-muted-foreground">{selectionLabel}</span>
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
          projects={projectsPage.items}
          pagination={{ total: projectsPage.total, limit: projectsLimit, offset: projectsOffset }}
          onPaginationChange={onProjectsPaginationChange}
          sort={projectsSort}
          onSortChange={onProjectsSortChange}
          search={projectsQuery}
          onSearchChange={onProjectsSearchChange}
          isLoading={projectsLoading}
          selectedIds={selectedIds}
          onSelectedIdsChange={setSelectedIds}
          onProjectOpen={(projectId) => router.push(`/projects/${projectId}`)}
        />
        </CardContent>
      </Card>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Supprimer les projets sélectionnés ?</AlertDialogTitle>
            <AlertDialogDescription>
              {selectedIds.size} projet(s){hasMultiplePages ? " (sur cette page)" : ""} seront supprimé(s) définitivement.
              Cette action est irréversible.
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
