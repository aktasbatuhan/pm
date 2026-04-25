"use client";

import { useEffect, useRef, useState } from "react";
import {
  fetchMe,
  getActiveTenantId,
  setActiveTenantId,
  type TenantInfo,
} from "@/lib/api";
import { Building2, Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export function TenantSwitcher() {
  const [tenants, setTenants] = useState<TenantInfo[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchMe().then((me) => {
      if (me.mode !== "postgres" || !me.tenants) return;
      setTenants(me.tenants);
      const stored = getActiveTenantId();
      const active =
        me.tenants.find((t) => t.id === stored) ??
        me.tenants.find((t) => t.is_default) ??
        me.tenants[0];
      if (active) {
        setActiveId(active.id);
        setActiveTenantId(active.id);
      }
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  if (tenants.length <= 1) return null;

  function handleSelect(t: TenantInfo) {
    if (t.id === activeId) {
      setOpen(false);
      return;
    }
    setActiveId(t.id);
    setActiveTenantId(t.id);
    setOpen(false);
    // Hard reload so every panel re-fetches with the new X-Tenant-Id header.
    window.location.reload();
  }

  const active = tenants.find((t) => t.id === activeId);
  const label = active?.name ?? active?.slug ?? "Workspace";

  return (
    <div className="relative" ref={rootRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <Building2 className="h-3 w-3" />
        <span className="max-w-[140px] truncate">{label}</span>
        <ChevronDown className="h-3 w-3 opacity-60" />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-60 rounded-lg border border-border bg-popover shadow-lg">
          <div className="border-b border-border px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Workspace
          </div>
          <div className="max-h-80 overflow-y-auto py-1">
            {tenants.map((t) => (
              <button
                key={t.id}
                onClick={() => handleSelect(t)}
                className={cn(
                  "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-[12px] hover:bg-muted",
                  t.id === activeId && "bg-muted/50"
                )}
              >
                <div>
                  <p className="font-medium">{t.name}</p>
                  <p className="text-[10px] text-muted-foreground">{t.slug} · {t.role}</p>
                </div>
                {t.id === activeId && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
