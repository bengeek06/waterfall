"use client";

import { Button } from "@/components/ui/button";

export type PlanningTreeToolbarProps = Readonly<{
  visible: boolean;
  showMoveActions: boolean;
  indentDisabled: boolean;
  outdentDisabled: boolean;
  moveUpDisabled: boolean;
  moveDownDisabled: boolean;
  onIndent: () => void;
  onOutdent: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  /**
   * Why a greyed-out move command is greyed out, when the reason is not readable from the table
   * itself -- INV-27 (#343): a jalon followed by siblings cannot be outdented, since outdenting it
   * would make those siblings its children. Rendered as a polite live region rather than a
   * `title` on the disabled button, which assistive technology would not reach.
   */
  notice?: string | null;
  showCreateAction: boolean;
  createDisabled: boolean;
  onCreateTask: () => void;
  showDeleteAction: boolean;
  deleteDisabled: boolean;
  onDeleteSelection: () => void;
}>;

// Extracted from PlanningTreeTable (E4-12 / #152): the Indenter/Désindenter/Monter/Descendre,
// "Ajouter une tâche" and "Supprimer la sélection" action bar. Renders nothing unless at least one
// action is actually offered, mirroring the original inline `showActionsToolbar` check.
export function PlanningTreeToolbar({
  visible,
  showMoveActions,
  indentDisabled,
  outdentDisabled,
  moveUpDisabled,
  moveDownDisabled,
  onIndent,
  onOutdent,
  onMoveUp,
  onMoveDown,
  notice = null,
  showCreateAction,
  createDisabled,
  onCreateTask,
  showDeleteAction,
  deleteDisabled,
  onDeleteSelection,
}: PlanningTreeToolbarProps) {
  if (!visible || !(showMoveActions || showCreateAction || showDeleteAction)) {
    return null;
  }
  return (
    <div className="mb-3 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {showMoveActions ? (
          <>
            <Button type="button" variant="outline" size="sm" disabled={indentDisabled} onClick={onIndent}>
              Indenter
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={outdentDisabled} onClick={onOutdent}>
              Désindenter
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={moveUpDisabled} onClick={onMoveUp}>
              Monter
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={moveDownDisabled} onClick={onMoveDown}>
              Descendre
            </Button>
          </>
        ) : null}
        {showCreateAction ? (
          <Button type="button" variant="outline" size="sm" disabled={createDisabled} onClick={onCreateTask}>
            Ajouter une tâche
          </Button>
        ) : null}
        {showDeleteAction ? (
          <Button type="button" variant="outline" size="sm" disabled={deleteDisabled} onClick={onDeleteSelection}>
            Supprimer la sélection
          </Button>
        ) : null}
      </div>
      {notice ? (
        <p role="status" className="text-xs text-muted-foreground">
          {notice}
        </p>
      ) : null}
    </div>
  );
}
