"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { RichResponse } from "@/components/rich-response";
import {
  fetchReportTemplates,
  createReportTemplate,
  updateReportTemplate,
  deleteReportTemplate,
  generateReport,
  fetchReports,
  deleteReport,
  fetchSignalSources,
  type ReportTemplate,
  type Report,
  type SignalSource,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  FileText,
  Plus,
  Trash2,
  Pencil,
  Check,
  X,
  Loader2,
  Calendar,
  Play,
  Copy,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
} from "lucide-react";

const STORAGE_KEY = "dash_reports_generating";

const LEARNING_CATEGORIES = ["risk", "team", "product", "process", "changelog", "technical"];
const BRIEF_DEPTHS = [
  { value: 1, label: "Latest brief" },
  { value: 3, label: "Last 3 briefs" },
  { value: 7, label: "Last week" },
];
const SCHEDULES = [
  { value: "none", label: "Manual only" },
  { value: "daily", label: "Daily at 9am" },
  { value: "weekly", label: "Weekly (Monday 9am)" },
  { value: "monthly", label: "Monthly (1st at 9am)" },
];

const TEMPLATE_PRESETS = [
  {
    name: "Weekly Stakeholder Update",
    body: `# Weekly Update — {{date}}

## What Shipped
{{recent_briefs}}

## Current Priorities
{{workspace}}

## Team Highlights
{{team_activity}}

## Risks & Blockers
{{learnings}}

## Signals from the Field
{{signals}}

## Next Week
What we're focused on next.`,
  },
  {
    name: "Monthly Board Report",
    body: `# Monthly Report — {{date}}

## Executive Summary
Three-sentence overview of the month.

## Product Progress
{{recent_briefs}}

## Metrics
Key numbers this month.

## Team
{{team_activity}}

## Risks
{{learnings}}

## Ask
What we need from the board.`,
  },
];

interface Props {
  onNavigateToChat: (prompt?: string) => void;
}

export function ReportsView({ onNavigateToChat }: Props) {
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [activeTemplateId, setActiveTemplateId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState(false);
  const [generating, setGenerating] = useState<string | null>(null);
  const [signalSources, setSignalSources] = useState<SignalSource[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    const [ts, ss] = await Promise.all([fetchReportTemplates(), fetchSignalSources()]);
    setTemplates(ts);
    setSignalSources(ss);
    if (!activeTemplateId && ts.length > 0) {
      setActiveTemplateId(ts[0].id);
    }
    setLoading(false);
  }, [activeTemplateId]);

  useEffect(() => { load(); }, [load]);

  // Restore generating state from localStorage
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        const { templateId, startedAt } = JSON.parse(stored);
        if (Date.now() - startedAt < 180_000) {
          setGenerating(templateId);
          pollForReport(templateId);
        } else {
          localStorage.removeItem(STORAGE_KEY);
        }
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
  }, []);

  function pollForReport(templateId: string) {
    let lastCount = 0;
    fetchReports(templateId, 1).then((r) => { lastCount = r.length; });
    const poll = setInterval(async () => {
      const reports = await fetchReports(templateId, 20);
      if (reports.length > lastCount) {
        setGenerating(null);
        localStorage.removeItem(STORAGE_KEY);
        clearInterval(poll);
        // Trigger a reload of the active template view
        load();
      }
    }, 5000);
    setTimeout(() => {
      clearInterval(poll);
      setGenerating(null);
      localStorage.removeItem(STORAGE_KEY);
    }, 180_000);
  }

  async function handleGenerate(templateId: string) {
    setGenerating(templateId);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ templateId, startedAt: Date.now() }));
    generateReport(templateId);
    pollForReport(templateId);
  }

  async function handleDeleteTemplate(id: string) {
    if (!confirm("Delete this template and all its reports?")) return;
    await deleteReportTemplate(id);
    if (activeTemplateId === id) setActiveTemplateId(null);
    load();
  }

  const activeTemplate = templates.find((t) => t.id === activeTemplateId);

  return (
    <div className="flex h-full">
      {/* ── Sidebar: templates ──────────────────────────────── */}
      <aside className="w-72 shrink-0 border-r border-border flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="text-sm font-semibold">Templates</h2>
          <button
            onClick={() => { setShowNew(true); setActiveTemplateId(null); setEditing(false); }}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted"
          >
            <Plus className="h-3 w-3" /> New
          </button>
        </div>

        <ScrollArea className="flex-1 px-2 py-2">
          {loading && templates.length === 0 ? (
            <div className="space-y-2 px-1">
              {[1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-md bg-muted" />)}
            </div>
          ) : templates.length === 0 && !showNew ? (
            <div className="px-3 py-8 text-center">
              <FileText className="mx-auto h-6 w-6 text-muted-foreground/30" />
              <p className="mt-2 text-xs text-muted-foreground">No templates yet</p>
              <button
                onClick={() => { setShowNew(true); }}
                className="mt-2 text-xs text-primary hover:underline"
              >
                Create your first
              </button>
            </div>
          ) : (
            <>
              {templates.map((t) => (
                <div key={t.id} className="group relative mb-0.5">
                  <button
                    onClick={() => { setActiveTemplateId(t.id); setShowNew(false); setEditing(false); }}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-md pl-2.5 pr-9 py-2 text-left transition-colors",
                      activeTemplateId === t.id ? "bg-muted" : "hover:bg-muted/60"
                    )}
                  >
                    <FileText className="h-3.5 w-3.5 shrink-0 opacity-60 mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <p className={cn("text-[13px] truncate", activeTemplateId === t.id ? "font-medium" : "text-muted-foreground")}>
                        {t.name}
                      </p>
                      <div className="flex items-center gap-2 mt-0.5">
                        {t.schedule !== "none" && (
                          <span className="text-[10px] text-primary">
                            <Calendar className="inline h-2.5 w-2.5 mr-0.5" />
                            {t.schedule}
                          </span>
                        )}
                        {t.report_count > 0 && (
                          <span className="text-[10px] text-muted-foreground">
                            {t.report_count} reports
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                  <button
                    onClick={() => handleDeleteTemplate(t.id)}
                    className="absolute right-1 top-1 opacity-0 group-hover:opacity-100 p-1 rounded text-muted-foreground hover:text-red-600 hover:bg-red-50"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </>
          )}
        </ScrollArea>
      </aside>

      {/* ── Main: editor or report ──────────────────────────── */}
      <div className="flex-1 overflow-hidden">
        {showNew || (activeTemplate && editing) ? (
          <TemplateEditor
            template={activeTemplate}
            signalSources={signalSources}
            onSaved={(id) => {
              setShowNew(false);
              setEditing(false);
              setActiveTemplateId(id);
              load();
            }}
            onCancel={() => {
              setShowNew(false);
              setEditing(false);
            }}
          />
        ) : activeTemplate ? (
          <TemplateDetail
            template={activeTemplate}
            isGenerating={generating === activeTemplate.id}
            onGenerate={() => handleGenerate(activeTemplate.id)}
            onEdit={() => setEditing(true)}
            onNavigateToChat={onNavigateToChat}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <FileText className="mx-auto h-10 w-10 text-muted-foreground/20" />
              <p className="mt-3 text-sm text-muted-foreground">Select or create a template</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Template detail (shows info + reports history) ───────────────────

function TemplateDetail({
  template,
  isGenerating,
  onGenerate,
  onEdit,
  onNavigateToChat,
}: {
  template: ReportTemplate;
  isGenerating: boolean;
  onGenerate: () => void;
  onEdit: () => void;
  onNavigateToChat: (prompt?: string) => void;
}) {
  const [reports, setReports] = useState<Report[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showTemplate, setShowTemplate] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await fetchReports(template.id, 20);
    setReports(r);
    if (r.length > 0 && !expanded) setExpanded(r[0].id);
  }, [template.id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!isGenerating) load();
  }, [isGenerating, load]);

  async function handleDelete(id: string) {
    if (!confirm("Delete this report?")) return;
    await deleteReport(id);
    load();
  }

  function handleCopy(id: string, content: string) {
    navigator.clipboard.writeText(content);
    setCopied(id);
    setTimeout(() => setCopied(null), 1500);
  }

  const resources = template.resources || {};

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-3xl px-8 py-8">
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{template.name}</h1>
            <div className="mt-2 flex items-center gap-3 text-sm text-muted-foreground">
              {template.schedule !== "none" && (
                <span className="inline-flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5" />
                  {SCHEDULES.find((s) => s.value === template.schedule)?.label}
                </span>
              )}
              <span>{reports.length} {reports.length === 1 ? "report" : "reports"}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onEdit}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted"
            >
              <Pencil className="h-3.5 w-3.5" /> Edit
            </button>
            <button
              onClick={onGenerate}
              disabled={isGenerating}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {isGenerating ? (
                <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating...</>
              ) : (
                <><Play className="h-3.5 w-3.5" /> Generate now</>
              )}
            </button>
          </div>
        </div>

        {isGenerating && (
          <div className="mb-6 flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <p className="text-sm text-primary font-medium">
              Generating report from template. Dash is pulling resources and synthesizing content...
            </p>
          </div>
        )}

        {/* Resources + Template collapsed */}
        <div className="mb-6 rounded-xl border border-border bg-card">
          <button
            onClick={() => setShowTemplate(!showTemplate)}
            className="flex w-full items-center justify-between px-4 py-3 text-sm"
          >
            <span className="font-medium">Template & resources</span>
            {showTemplate ? <EyeOff className="h-4 w-4 text-muted-foreground" /> : <Eye className="h-4 w-4 text-muted-foreground" />}
          </button>
          {showTemplate && (
            <div className="border-t border-border px-4 py-3 space-y-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Resources</p>
                <div className="flex flex-wrap gap-1.5">
                  {resources.learning_categories?.map((c) => (
                    <Badge key={c} variant="secondary" className="text-[10px]">{c}</Badge>
                  ))}
                  {resources.brief_depth && (
                    <Badge variant="secondary" className="text-[10px]">
                      Last {resources.brief_depth} brief{resources.brief_depth > 1 ? "s" : ""}
                    </Badge>
                  )}
                  {resources.signal_sources?.map((s) => (
                    <Badge key={s} variant="secondary" className="text-[10px]">signal: {s}</Badge>
                  ))}
                  {!resources.learning_categories?.length && !resources.brief_depth && !resources.signal_sources?.length && (
                    <span className="text-xs text-muted-foreground">No specific resources — uses general workspace context</span>
                  )}
                </div>
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Template</p>
                <pre className="rounded-md bg-muted p-3 text-xs font-mono whitespace-pre-wrap max-h-60 overflow-y-auto">
                  {template.body}
                </pre>
              </div>
            </div>
          )}
        </div>

        {/* Reports history */}
        {reports.length === 0 && !isGenerating ? (
          <Card>
            <CardContent className="py-10 text-center">
              <FileText className="mx-auto h-8 w-8 text-muted-foreground/30" />
              <p className="mt-3 text-sm font-medium text-muted-foreground">No reports yet</p>
              <p className="mt-1 text-xs text-muted-foreground">Click Generate now to create the first one</p>
            </CardContent>
          </Card>
        ) : (
          <div className="relative ml-4">
            <div className="absolute left-0 top-2 bottom-2 w-px bg-border" />
            {reports.map((r, i) => {
              const isExpanded = expanded === r.id;
              const isLatest = i === 0;
              return (
                <div key={r.id} className="relative pl-8 pb-6 last:pb-0">
                  <div className="absolute left-0 -translate-x-1/2 top-1.5">
                    <div className={cn("h-3 w-3 rounded-full border-2 border-background", isLatest ? "bg-primary" : "bg-muted-foreground/30")} />
                  </div>

                  <div className="flex items-center justify-between">
                    <button
                      onClick={() => setExpanded(isExpanded ? null : r.id)}
                      className="flex items-center gap-3 text-left"
                    >
                      <span className={cn("text-sm font-medium", isLatest ? "text-foreground" : "text-muted-foreground")}>
                        {new Date(r.created_at * 1000).toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                      {isLatest && <Badge variant="secondary" className="text-[10px]">Latest</Badge>}
                      {isExpanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
                    </button>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleCopy(r.id, r.content)}
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted"
                      >
                        {copied === r.id ? <><Check className="h-3 w-3 text-green-500" /> Copied</> : <><Copy className="h-3 w-3" /> Copy</>}
                      </button>
                      <button
                        onClick={() => handleDelete(r.id)}
                        className="rounded-md p-1 text-muted-foreground hover:text-red-600 hover:bg-red-50"
                      >
                        <Trash2 className="h-3 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="mt-3 rounded-xl border border-border bg-card px-5 py-4 animate-in fade-in slide-in-from-top-2 duration-200">
                      <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none">
                        <RichResponse>{r.content}</RichResponse>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="h-16" />
      </div>
    </ScrollArea>
  );
}

// ── Template editor ──────────────────────────────────────────────────

function TemplateEditor({
  template,
  signalSources,
  onSaved,
  onCancel,
}: {
  template?: ReportTemplate;
  signalSources: SignalSource[];
  onSaved: (id: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(template?.name || "");
  const [body, setBody] = useState(template?.body || "");
  const [schedule, setSchedule] = useState(template?.schedule || "none");
  const [learningCats, setLearningCats] = useState<string[]>(template?.resources?.learning_categories ?? []);
  const [briefDepth, setBriefDepth] = useState<number>(template?.resources?.brief_depth ?? 0);
  const [sigSources, setSigSources] = useState<string[]>(template?.resources?.signal_sources ?? []);
  const [saving, setSaving] = useState(false);

  const isEdit = !!template;

  function togglePreset(preset: typeof TEMPLATE_PRESETS[0]) {
    setName(preset.name);
    setBody(preset.body);
  }

  async function handleSave() {
    if (!name.trim() || !body.trim()) return;
    setSaving(true);
    const payload = {
      name: name.trim(),
      body: body.trim(),
      schedule,
      resources: {
        learning_categories: learningCats,
        brief_depth: briefDepth || undefined,
        signal_sources: sigSources,
      },
    };
    let id = template?.id ?? "";
    if (isEdit && template) {
      await updateReportTemplate(template.id, payload);
      id = template.id;
    } else {
      const result = await createReportTemplate(payload);
      id = result.id;
    }
    setSaving(false);
    onSaved(id);
  }

  function toggleCat(c: string) {
    setLearningCats((prev) => prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]);
  }

  function toggleSig(s: string) {
    setSigSources((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]);
  }

  return (
    <div className="flex h-full">
      {/* Left: form */}
      <div className="w-1/2 border-r border-border overflow-hidden flex flex-col">
        <div className="flex items-center justify-between border-b border-border px-6 py-3">
          <h2 className="text-sm font-semibold">{isEdit ? "Edit template" : "New template"}</h2>
          <div className="flex gap-2">
            <button
              onClick={onCancel}
              className="rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!name.trim() || !body.trim() || saving}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
              Save
            </button>
          </div>
        </div>

        <ScrollArea className="flex-1">
          <div className="px-6 py-4 space-y-5">
            {/* Name */}
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Weekly Stakeholder Update"
                className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/40"
              />
            </div>

            {/* Presets */}
            {!isEdit && (
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">Start from preset</label>
                <div className="flex flex-wrap gap-2">
                  {TEMPLATE_PRESETS.map((p) => (
                    <button
                      key={p.name}
                      onClick={() => togglePreset(p)}
                      className="rounded-full border border-border bg-card px-3 py-1 text-[11px] text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Body */}
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">
                Markdown template
              </label>
              <p className="text-[11px] text-muted-foreground mb-2">
                Use placeholders like <code className="bg-muted px-1 py-0.5 rounded text-[10px]">{"{{recent_briefs}}"}</code>,{" "}
                <code className="bg-muted px-1 py-0.5 rounded text-[10px]">{"{{team_activity}}"}</code>,{" "}
                <code className="bg-muted px-1 py-0.5 rounded text-[10px]">{"{{learnings}}"}</code>,{" "}
                <code className="bg-muted px-1 py-0.5 rounded text-[10px]">{"{{signals}}"}</code>,{" "}
                <code className="bg-muted px-1 py-0.5 rounded text-[10px]">{"{{workspace}}"}</code>,{" "}
                <code className="bg-muted px-1 py-0.5 rounded text-[10px]">{"{{date}}"}</code>
              </p>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={18}
                placeholder="# My Report&#10;&#10;## Section&#10;{{recent_briefs}}"
                className="w-full rounded-md border border-border bg-card px-3 py-2 text-xs font-mono leading-relaxed outline-none resize-none focus:border-primary/40"
              />
            </div>

            {/* Resources */}
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">
                Resources the agent should pull
              </label>

              <div className="space-y-3">
                <div>
                  <p className="text-[11px] text-muted-foreground mb-1.5">Learning categories</p>
                  <div className="flex flex-wrap gap-1.5">
                    {LEARNING_CATEGORIES.map((c) => (
                      <button
                        key={c}
                        onClick={() => toggleCat(c)}
                        className={cn(
                          "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors",
                          learningCats.includes(c)
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-border text-muted-foreground hover:border-primary/30"
                        )}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <p className="text-[11px] text-muted-foreground mb-1.5">Brief history depth</p>
                  <div className="flex flex-wrap gap-1.5">
                    {BRIEF_DEPTHS.map((d) => (
                      <button
                        key={d.value}
                        onClick={() => setBriefDepth(briefDepth === d.value ? 0 : d.value)}
                        className={cn(
                          "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors",
                          briefDepth === d.value
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-border text-muted-foreground hover:border-primary/30"
                        )}
                      >
                        {d.label}
                      </button>
                    ))}
                  </div>
                </div>

                {signalSources.length > 0 && (
                  <div>
                    <p className="text-[11px] text-muted-foreground mb-1.5">Signal sources</p>
                    <div className="flex flex-wrap gap-1.5">
                      {signalSources.map((s) => (
                        <button
                          key={s.id}
                          onClick={() => toggleSig(s.name)}
                          className={cn(
                            "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors",
                            sigSources.includes(s.name)
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-border text-muted-foreground hover:border-primary/30"
                          )}
                        >
                          {s.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Schedule */}
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">
                Automatic generation
              </label>
              <div className="flex flex-wrap gap-1.5">
                {SCHEDULES.map((s) => (
                  <button
                    key={s.value}
                    onClick={() => setSchedule(s.value as ReportTemplate["schedule"])}
                    className={cn(
                      "rounded-md border px-3 py-1.5 text-xs transition-colors",
                      schedule === s.value
                        ? "border-primary bg-primary/10 text-primary font-medium"
                        : "border-border text-muted-foreground hover:border-primary/30"
                    )}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </ScrollArea>
      </div>

      {/* Right: live preview */}
      <div className="w-1/2 overflow-hidden flex flex-col">
        <div className="border-b border-border px-6 py-3">
          <h2 className="text-sm font-semibold">Preview</h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            How the template renders (placeholders stay visible until generated)
          </p>
        </div>
        <ScrollArea className="flex-1 px-8 py-6">
          <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none">
            <RichResponse>{body || "*Empty template — add content on the left.*"}</RichResponse>
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
