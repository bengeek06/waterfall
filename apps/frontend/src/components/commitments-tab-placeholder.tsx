"use client";

export type CommitmentsTabPlaceholderProps = {
  active: boolean;
};

// Extracted from ProjectDetailsPage (E4-11 / #151): the trivial "Reste à engager" placeholder,
// gated the same way as the other tabs (via the `active` prop) for consistency. Verbatim JSX
// move -- see page.tsx call site for wiring.
export function CommitmentsTabPlaceholder({ active }: CommitmentsTabPlaceholderProps) {
  if (!active) {
    return null;
  }

  return (
    <div className="grid min-h-45 content-center justify-items-start gap-4">
      <h2>Reste à engager</h2>
      <p className="text-sm text-muted-foreground">
        Le suivi budget de référence / engagé / reste à engager sera construit sur les versions
        « forecast_remaining » du jalon 9.
      </p>
    </div>
  );
}
