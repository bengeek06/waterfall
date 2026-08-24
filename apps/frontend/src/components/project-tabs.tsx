"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

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
    <Tabs value={activeTab} onValueChange={(value) => onChange(value as ProjectTab)}>
      <TabsList aria-label="Sections du projet" className="h-auto w-full justify-start overflow-x-auto rounded-none border-b bg-transparent p-0">
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
