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

export function SettingsTabs({
  activeTab,
  onChange,
}: SettingsTabsProps) {
  return (
    <Tabs
      value={activeTab}
      onValueChange={(value) => onChange(value as SettingsTab)}
      className="w-full"
    >
      <TabsList
        aria-label="Sections des paramètres"
        className="
          h-auto
          w-full
          justify-start
          gap-1
          overflow-x-auto
          rounded-lg
          p-1
        "
      >
        {tabs.map(([tab, label]) => (
          <TabsTrigger
            key={tab}
            value={tab}
            className="
              h-10
              shrink-0
              flex-none
              px-4
              py-0

              text-sm
              font-medium

              data-active:text-foreground
              data-active:font-semibold
              data-active:shadow-sm
            "
          >
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}