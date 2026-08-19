"use client";

import type { FormEventHandler } from "react";
import type { ResourceNode } from "@/lib/backend";

export type OrganizationRow = ResourceNode & { depth: number; hasChildren: boolean };

type OrganizationTreeProps = {
  rows: OrganizationRow[];
  selectedNodeId: number | null;
  collapsedNodeIds: Set<number>;
  editingNodeId: number | null;
  nodeCode: string;
  nodeName: string;
  nodeParentId: string;
  nodeDraft: { code: string; name: string; parentId: string };
  actionBusy: boolean;
  onAdd: FormEventHandler<HTMLFormElement>;
  onSelect: (nodeId: number) => void;
  onToggleCollapsed: (nodeId: number) => void;
  onStartEdit: (node: ResourceNode) => void;
  onDraftChange: (field: "code" | "name" | "parentId", value: string) => void;
  onSave: (node: ResourceNode) => void;
  onCancel: () => void;
  onRemove: (node: ResourceNode) => void;
  onNodeChange: (field: "code" | "name" | "parent", value: string) => void;
};

export function OrganizationTree(props: OrganizationTreeProps) {
  return (
    <section className="panel panel-stack">
      <h2>Organisation</h2>
      <form onSubmit={props.onAdd}>
        <div className="table-scroll">
          <table className="table organization-table">
            <thead><tr><th scope="col">Code</th><th scope="col">Nom</th><th scope="col">Actions</th></tr></thead>
            <tbody>
              <tr>
                <td><input aria-label="Code du nouveau nœud" value={props.nodeCode} onChange={(event) => props.onNodeChange("code", event.target.value)} required /></td>
                <td><input aria-label="Nom du nouveau nœud" value={props.nodeName} onChange={(event) => props.onNodeChange("name", event.target.value)} required /></td>
                <td><div className="row"><select aria-label="Parent du nouveau nœud" value={props.nodeParentId} onChange={(event) => props.onNodeChange("parent", event.target.value)}><option value="">Racine</option>{props.rows.map((node) => <option key={node.id} value={node.id}>{"  ".repeat(node.depth)}{node.code} - {node.name}</option>)}</select><button className="btn btn-primary" disabled={props.actionBusy} type="submit">Ajouter</button></div></td>
              </tr>
              {props.rows.map((node) => {
                const editing = props.editingNodeId === node.id;
                return <tr key={node.id} className={props.selectedNodeId === node.id ? "organization-row-selected" : ""} onClick={() => props.onSelect(node.id)}>
                  <td><div className="row" style={{ gap: "0.35rem", paddingLeft: `${node.depth * 1.25}rem` }}>{node.hasChildren ? <button className="btn btn-icon" type="button" aria-label={props.collapsedNodeIds.has(node.id) ? `Déplier ${node.name}` : `Replier ${node.name}`} onClick={(event) => { event.stopPropagation(); props.onToggleCollapsed(node.id); }}>{props.collapsedNodeIds.has(node.id) ? "▸" : "▾"}</button> : <span style={{ width: "2rem" }} />}{editing ? <input aria-label={`Code de ${node.name}`} value={props.nodeDraft.code} onChange={(event) => props.onDraftChange("code", event.target.value)} /> : <strong>{node.code}</strong>}</div></td>
                  <td>{editing ? <input aria-label={`Nom de ${node.code}`} value={props.nodeDraft.name} onChange={(event) => props.onDraftChange("name", event.target.value)} /> : <span>{node.name}</span>}</td>
                  <td className="table-actions">{editing ? <div className="row"><select aria-label={`Parent de ${node.code}`} value={props.nodeDraft.parentId} onChange={(event) => props.onDraftChange("parentId", event.target.value)}><option value="">Racine</option>{props.rows.filter((candidate) => candidate.id !== node.id).map((candidate) => <option key={candidate.id} value={candidate.id}>{"  ".repeat(candidate.depth)}{candidate.code} - {candidate.name}</option>)}</select><button className="btn btn-primary" type="button" disabled={props.actionBusy} onClick={(event) => { event.stopPropagation(); props.onSave(node); }}>Enregistrer</button><button className="btn" type="button" onClick={(event) => { event.stopPropagation(); props.onCancel(); }}>Annuler</button></div> : <div className="row"><button className="btn" type="button" onClick={(event) => { event.stopPropagation(); props.onStartEdit(node); }}>Modifier</button><button className="btn btn-danger" type="button" disabled={props.actionBusy} onClick={(event) => { event.stopPropagation(); props.onRemove(node); }}>Supprimer</button></div>}</td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>
      </form>
    </section>
  );
}