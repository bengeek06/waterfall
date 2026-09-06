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
    <div className="mb-3 flex flex-wrap items-center gap-2">
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
  );
}
