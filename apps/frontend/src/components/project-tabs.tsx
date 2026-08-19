"use client";

export type ProjectTab = "planning" | "estimate" | "commitments" | "analytics";

type ProjectTabsProps = {
  activeTab: ProjectTab;
  onChange: (tab: ProjectTab) => void;
};

const tabs: Array<[ProjectTab, string]> = [
  ["planning", "Planning"],
  ["estimate", "Devis"],
  ["commitments", "Reste à engager"],
  ["analytics", "Analytique"],
];

export function ProjectTabs({ activeTab, onChange }: ProjectTabsProps) {
  return (
    <nav className="project-tabs" aria-label="Sections du projet">
      {tabs.map(([tab, label]) => (
        <button
          key={tab}
          className={`project-tab ${activeTab === tab ? "project-tab-active" : ""}`}
          type="button"
          aria-selected={activeTab === tab}
          role="tab"
          onClick={() => onChange(tab)}
        >
          {label}
        </button>
      ))}
    </nav>
  );
}
