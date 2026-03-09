import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DashboardResponse, ProjectItem } from "@/types/api";

const priorityColors: Record<string, string> = {
  "Urgent": "text-destructive",
  "High": "text-orange-400",
  "Medium": "text-warning",
  "Low": "text-muted-foreground",
};

const statusColors: Record<string, string> = {
  "Done": "text-success",
  "In Progress": "text-primary",
  "Todo": "text-muted-foreground",
  "Blocked": "text-destructive",
};

export function ProjectPage() {
  const [filters, setFilters] = useState<Record<string, string>>({});

  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiGet<DashboardResponse>("/dashboard"),
    refetchInterval: 60_000,
  });

  const filteredItems = data?.items.filter((item) => {
    if (filters.status && item.status !== filters.status) return false;
    if (filters.priority && item.priority !== filters.priority) return false;
    if (filters.assignee && !item.assignees.includes(filters.assignee)) return false;
    if (filters.repository && item.repository !== filters.repository) return false;
    return true;
  }) ?? [];

  const overview = data?.stats.overview;

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Project Board</h1>
        <p className="text-xs text-muted-foreground mt-0.5">GitHub project items and sprint tracking</p>
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-md p-3 mb-4">
          <p className="text-xs text-destructive">{(error as Error).message}</p>
        </div>
      )}

      {/* Stat cards */}
      {overview && (
        <div className="grid grid-cols-4 gap-3 mb-6">
          <StatCard label="TOTAL" value={overview.total} />
          <StatCard label="COMPLETION" value={`${overview.completionPct}%`} color="text-success" />
          <StatCard label="IN PROGRESS" value={overview.inProgressCount} color="text-primary" />
          <StatCard label="BLOCKED" value={overview.blocked} color={overview.blocked > 0 ? "text-destructive" : undefined} />
        </div>
      )}

      {/* Filter bar */}
      {data?.filters && (
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          <FilterSelect
            label="Status"
            value={filters.status}
            options={data.filters.statuses}
            onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
          />
          <FilterSelect
            label="Priority"
            value={filters.priority}
            options={data.filters.priorities}
            onChange={(v) => setFilters((f) => ({ ...f, priority: v }))}
          />
          <FilterSelect
            label="Assignee"
            value={filters.assignee}
            options={data.filters.assignees}
            onChange={(v) => setFilters((f) => ({ ...f, assignee: v }))}
          />
          <FilterSelect
            label="Repo"
            value={filters.repository}
            options={data.filters.repositories}
            onChange={(v) => setFilters((f) => ({ ...f, repository: v }))}
          />
          {Object.keys(filters).some((k) => filters[k]) && (
            <button
              onClick={() => setFilters({})}
              className="text-[10px] text-muted-foreground hover:text-foreground transition-colors px-2 py-1"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* Items table */}
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="bg-card border border-border rounded-md h-10 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="border border-border rounded-md overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-muted/30 border-b border-border">
                <th className="text-left px-3 py-2 label-uppercase font-normal">Title</th>
                <th className="text-left px-3 py-2 label-uppercase font-normal w-24">Status</th>
                <th className="text-left px-3 py-2 label-uppercase font-normal w-20">Priority</th>
                <th className="text-left px-3 py-2 label-uppercase font-normal w-28">Assignee</th>
                <th className="text-left px-3 py-2 label-uppercase font-normal w-32">Repo</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.map((item, i) => (
                <ItemRow key={`${item.title}-${i}`} item={item} />
              ))}
              {filteredItems.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center py-8 text-muted-foreground">
                    No items match filters
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between mt-3">
        <span className="text-[10px] text-muted-foreground">
          {filteredItems.length} item{filteredItems.length !== 1 ? "s" : ""}
          {data?.fetchedAt && ` · Updated ${new Date(data.fetchedAt).toLocaleTimeString()}`}
        </span>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="bg-card border border-border rounded-md px-4 py-3">
      <span className="label-uppercase">{label}</span>
      <p className={cn("text-xl font-bold mt-1", color || "text-foreground")}>{value}</p>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value?: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
      className="bg-card border border-border rounded-md px-2 py-1 text-[10px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
    >
      <option value="">{label}: All</option>
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  );
}

function ItemRow({ item }: { item: ProjectItem }) {
  return (
    <tr className="border-b border-border last:border-0 hover:bg-muted/20 transition-colors">
      <td className="px-3 py-2">
        {item.issue_url ? (
          <a
            href={item.issue_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-foreground hover:text-primary transition-colors"
          >
            {item.title}
          </a>
        ) : (
          <span className="text-foreground">{item.title}</span>
        )}
      </td>
      <td className="px-3 py-2">
        <span className={cn(statusColors[item.status || ""] || "text-muted-foreground")}>
          {item.status || "—"}
        </span>
      </td>
      <td className="px-3 py-2">
        <span className={cn(priorityColors[item.priority || ""] || "text-muted-foreground")}>
          {item.priority || "—"}
        </span>
      </td>
      <td className="px-3 py-2 text-muted-foreground">
        {item.assignees.length > 0 ? item.assignees.join(", ") : "—"}
      </td>
      <td className="px-3 py-2 text-muted-foreground truncate">{item.repository || "—"}</td>
    </tr>
  );
}
