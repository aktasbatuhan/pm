"use client";

import { useEffect, useRef, useState } from "react";
import { fetchModelSetting, updateModelSetting, type ModelOption } from "@/lib/api";
import { Cpu, Check, ChevronDown, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function ModelSelector() {
  const [current, setCurrent] = useState<string | null>(null);
  const [options, setOptions] = useState<ModelOption[]>([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchModelSetting().then((s) => {
      if (s) {
        setCurrent(s.current);
        setOptions(s.options);
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

  async function handleSelect(id: string) {
    if (id === current) {
      setOpen(false);
      return;
    }
    setSaving(true);
    const result = await updateModelSetting(id);
    setSaving(false);
    if (result.ok) {
      setCurrent(result.current || id);
      setOpen(false);
    } else {
      alert(result.error || "Failed to update model");
    }
  }

  const label = options.find((o) => o.id === current)?.label || current || "Model";

  return (
    <div className="relative" ref={rootRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={saving}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
      >
        {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Cpu className="h-3 w-3" />}
        <span className="max-w-[140px] truncate">{label}</span>
        <ChevronDown className="h-3 w-3 opacity-60" />
      </button>

      {open && options.length > 0 && (
        <div className="absolute right-0 top-full z-50 mt-1 w-60 rounded-lg border border-border bg-popover shadow-lg">
          <div className="border-b border-border px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Agent model
          </div>
          <div className="max-h-80 overflow-y-auto py-1">
            {options.map((o) => (
              <button
                key={o.id}
                onClick={() => handleSelect(o.id)}
                className={cn(
                  "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-[12px] hover:bg-muted",
                  o.id === current && "bg-muted/50"
                )}
              >
                <div>
                  <p className="font-medium">{o.label}</p>
                  <p className="text-[10px] text-muted-foreground">{o.id}</p>
                </div>
                {o.id === current && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
