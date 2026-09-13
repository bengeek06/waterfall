"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type ProjectTab =
  | "planning"
  | "estimate"
  | "commitments"
  | "analytics";

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

export function ProjectTabs({
  activeTab,
  onChange,
}: ProjectTabsProps) {
  return (
    <Tabs
      value={activeTab}
      onValueChange={(value) => onChange(value as ProjectTab)}
      className="w-full"
    >
      <TabsList
        aria-label="Sections du projet"
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
