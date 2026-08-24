"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

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
    <Tabs value={activeTab} onValueChange={(value) => onChange(value as SettingsTab)}>
      <TabsList aria-label="Sections des paramètres" className="h-auto w-full justify-start overflow-x-auto rounded-none border-b bg-transparent p-0">
        {tabs.map(([tab, label]) => (
          <TabsTrigger
            key={tab}
            value={tab}
            className="shrink-0 rounded-none border-b-2 border-transparent px-3 py-2.5 text-sm data-active:border-primary data-active:bg-transparent"
          >
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}