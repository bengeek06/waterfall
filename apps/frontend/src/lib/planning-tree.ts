import type { Task } from "./backend";

export type PlanningMoveCommand = {
  task_uids: number[];
  target_parent_uid: number | null;
  position: number;
};

type SiblingIndex = {
  parentUid: number | null;
  siblings: Task[];
};

function buildChildrenByParent(tasks: Task[]): Map<number | null, Task[]> {
  const knownUids = new Set(tasks.map((task) => task.uid));
  const childrenByParent = new Map<number | null, Task[]>();
  for (const task of tasks) {
    const parentKey =
      task.parent_uid !== null && task.parent_uid !== undefined && knownUids.has(task.parent_uid)
        ? task.parent_uid
        : null;
    const siblings = childrenByParent.get(parentKey) ?? [];
    siblings.push(task);
    childrenByParent.set(parentKey, siblings);
  }
  for (const siblings of childrenByParent.values()) {
    siblings.sort((a, b) => (a.position ?? Number.POSITIVE_INFINITY) - (b.position ?? Number.POSITIVE_INFINITY));
  }
  return childrenByParent;
}

// Mirrors the backend's _selected_roots: a descendant is dropped when an ancestor is also selected,
// since it moves implicitly with that ancestor. Order follows tree (depth-first) order.
export function normalizeSelectionToRoots(tasks: Task[], selectedUids: ReadonlySet<number>): Task[] {
  const tasksByUid = new Map(tasks.map((task) => [task.uid, task]));
  const childrenByParent = buildChildrenByParent(tasks);

  function hasSelectedAncestor(task: Task): boolean {
    let parentUid = task.parent_uid ?? null;
    while (parentUid !== null && parentUid !== undefined) {
      if (selectedUids.has(parentUid)) {
        return true;
      }
      parentUid = tasksByUid.get(parentUid)?.parent_uid ?? null;
    }
    return false;
  }

  const rootUids = new Set(
    tasks.filter((task) => selectedUids.has(task.uid) && !hasSelectedAncestor(task)).map((task) => task.uid),
  );

  const ordered: Task[] = [];
  function walk(parentUid: number | null) {
    for (const task of childrenByParent.get(parentUid) ?? []) {
      if (rootUids.has(task.uid)) {
        ordered.push(task);
      }
      walk(task.uid);
    }
  }
  walk(null);
  return ordered;
}

function siblingsOf(task: Task, tasks: Task[]): SiblingIndex {
  const childrenByParent = buildChildrenByParent(tasks);
  const parentUid = task.parent_uid ?? null;
  return { parentUid, siblings: childrenByParent.get(parentUid) ?? [] };
}

export function computeIndentCommand(
  tasks: Task[],
  selectedUids: ReadonlySet<number>,
): PlanningMoveCommand | null {
  const roots = normalizeSelectionToRoots(tasks, selectedUids);
  if (!roots.length) {
    return null;
  }
  const first = roots[0];
  const { siblings } = siblingsOf(first, tasks);
  const index = siblings.findIndex((sibling) => sibling.uid === first.uid);
  const previousSibling = siblings[index - 1];
  if (index <= 0 || !previousSibling || previousSibling.is_milestone) {
    // The move endpoint rejects a milestone as a parent; keep the action disabled instead of erroring.
    return null;
  }
  const childrenByParent = buildChildrenByParent(tasks);
  const newSiblingCount = (childrenByParent.get(previousSibling.uid) ?? []).length;
  return {
    task_uids: roots.map((task) => task.uid),
    target_parent_uid: previousSibling.uid,
    position: newSiblingCount + 1,
  };
}

export function computeOutdentCommand(
  tasks: Task[],
  selectedUids: ReadonlySet<number>,
): PlanningMoveCommand | null {
  const roots = normalizeSelectionToRoots(tasks, selectedUids);
  if (!roots.length) {
    return null;
  }
  const first = roots[0];
  const currentParentUid = first.parent_uid ?? null;
  if (currentParentUid === null) {
    return null;
  }
  const tasksByUid = new Map(tasks.map((task) => [task.uid, task]));
  const currentParent = tasksByUid.get(currentParentUid);
  if (!currentParent) {
    return null;
  }
  const grandParentUid = currentParent.parent_uid ?? null;
  // Derive the insertion point from the sorted sibling list: position is nullable and not unique,
  // so it cannot be used directly to place the task right after its former parent.
  const { siblings: grandSiblings } = siblingsOf(currentParent, tasks);
  const currentParentIndex = grandSiblings.findIndex((sibling) => sibling.uid === currentParentUid);
  return {
    task_uids: roots.map((task) => task.uid),
    target_parent_uid: grandParentUid,
    position: currentParentIndex + 2,
  };
}

export function computeReorderCommand(
  tasks: Task[],
  selectedUids: ReadonlySet<number>,
  direction: "up" | "down",
): PlanningMoveCommand | null {
  const roots = normalizeSelectionToRoots(tasks, selectedUids);
  if (!roots.length) {
    return null;
  }
  const parentUid = roots[0].parent_uid ?? null;
  if (roots.some((task) => (task.parent_uid ?? null) !== parentUid)) {
    return null;
  }
  const { siblings } = siblingsOf(roots[0], tasks);
  const rootUids = new Set(roots.map((task) => task.uid));
  const indices = siblings.map((sibling, index) => (rootUids.has(sibling.uid) ? index : -1)).filter((index) => index >= 0);
  const minIndex = Math.min(...indices);
  const maxIndex = Math.max(...indices);
  if (maxIndex - minIndex + 1 !== indices.length) {
    // Selected siblings are not a contiguous block; reordering them as one move is ambiguous.
    return null;
  }
  const remaining = siblings.filter((sibling) => !rootUids.has(sibling.uid));

  if (direction === "up") {
    const anchorBefore = siblings[minIndex - 1];
    if (!anchorBefore) {
      return null;
    }
    const anchorIndex = remaining.findIndex((sibling) => sibling.uid === anchorBefore.uid);
    return { task_uids: roots.map((task) => task.uid), target_parent_uid: parentUid, position: anchorIndex + 1 };
  }

  const anchorAfter = siblings[maxIndex + 1];
  if (!anchorAfter) {
    return null;
  }
  const anchorIndex = remaining.findIndex((sibling) => sibling.uid === anchorAfter.uid);
  return { task_uids: roots.map((task) => task.uid), target_parent_uid: parentUid, position: anchorIndex + 2 };
}
