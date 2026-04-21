import type { MetadataRoute } from "next";

const BASE = "https://heydash.dev";

const ROLES = ["product-managers", "founders", "engineering-leads"];
const USE_CASES = [
  "daily-standups",
  "sprint-retrospectives",
  "stakeholder-updates",
  "team-health-monitoring",
  "signal-collection",
  "report-automation",
];
const COMPARISONS = [
  "vs-linear-insights",
  "vs-notion-pm",
  "vs-manual-standups",
  "vs-spreadsheet-reporting",
];
const GLOSSARY = [
  "daily-brief",
  "product-signals",
  "team-pulse",
  "autonomous-pm",
  "action-items",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date().toISOString();

  const staticPages = [
    { url: BASE, lastModified: now, changeFrequency: "weekly" as const, priority: 1.0 },
    { url: `${BASE}/claim`, lastModified: now, changeFrequency: "monthly" as const, priority: 0.9 },
  ];

  const rolePages = ROLES.map((r) => ({
    url: `${BASE}/for/${r}`,
    lastModified: now,
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }));

  const useCasePages = USE_CASES.map((u) => ({
    url: `${BASE}/use-cases/${u}`,
    lastModified: now,
    changeFrequency: "monthly" as const,
    priority: 0.7,
  }));

  const comparisonPages = COMPARISONS.map((c) => ({
    url: `${BASE}/compare/${c}`,
    lastModified: now,
    changeFrequency: "monthly" as const,
    priority: 0.6,
  }));

  const glossaryPages = GLOSSARY.map((g) => ({
    url: `${BASE}/glossary/${g}`,
    lastModified: now,
    changeFrequency: "monthly" as const,
    priority: 0.5,
  }));

  return [...staticPages, ...rolePages, ...useCasePages, ...comparisonPages, ...glossaryPages];
}
