"use client";

export type SettingsTab = "resources" | "costs" | "users";

type SettingsTabsProps = {
  activeTab: SettingsTab;
  onChange: (tab: SettingsTab) => void;
};

const tabs: Array<[SettingsTab, string]> = [
  ["costs", "Coûts"],
  ["resources", "Ressources"],
  ["users", "Utilisateurs"],
];

export function SettingsTabs({ activeTab, onChange }: SettingsTabsProps) {
  return (
    <nav className="project-tabs" aria-label="Sections des paramètres">
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