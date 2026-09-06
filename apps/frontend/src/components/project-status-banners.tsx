"use client";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export type ProjectStatusBannersProps = {
  busy: boolean;
  error: string | null;
  retryableActionMessage: string | null;
  importFeedback: string | null;
  onRetry: () => void;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the cross-tab busy/error/import-feedback
// banners rendered above the active tab's content. Verbatim JSX move -- see page.tsx call site
// for wiring.
export function ProjectStatusBanners({
  busy,
  error,
  retryableActionMessage,
  importFeedback,
  onRetry,
}: ProjectStatusBannersProps) {
  return (
    <>
      {busy ? <p className="text-sm text-muted-foreground" role="status">Chargement...</p> : null}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>
            {error}
            {retryableActionMessage === error ? (
              <div className="mt-2">
                <Button size="sm" onClick={onRetry}>
                  Réessayer
                </Button>
              </div>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}
      {importFeedback ? <Alert><AlertDescription>{importFeedback}</AlertDescription></Alert> : null}
    </>
  );
}
