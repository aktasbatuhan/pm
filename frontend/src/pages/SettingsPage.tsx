import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPut } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check } from "lucide-react";
import type { SetupStatus, SettingsMap } from "@/types/api";

interface SettingField {
  key: string;
  label: string;
  placeholder: string;
  sensitive?: boolean;
  group: string;
}

const settingFields: SettingField[] = [
  { key: "integration.exa_api_key", label: "Exa API Key", placeholder: "exa-...", sensitive: true, group: "Integrations" },
  { key: "integration.posthog_api_key", label: "PostHog API Key", placeholder: "phx_...", sensitive: true, group: "Integrations" },
  { key: "integration.posthog_host", label: "PostHog Host", placeholder: "https://app.posthog.com", group: "Integrations" },
  { key: "integration.posthog_project_id", label: "PostHog Project ID", placeholder: "12345", group: "Integrations" },
  { key: "integration.slack_webhook_url", label: "Slack Webhook URL", placeholder: "https://hooks.slack.com/...", sensitive: true, group: "Integrations" },
  { key: "integration.linear_api_key", label: "Linear API Key", placeholder: "lin_api_...", sensitive: true, group: "Integrations" },
  { key: "slack.allowed_users", label: "Allowed Slack Users", placeholder: "user1,user2", group: "Slack" },
  { key: "slack.allowed_channels", label: "Allowed Slack Channels", placeholder: "channel1,channel2", group: "Slack" },
];

export function SettingsPage() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const queryClient = useQueryClient();

  const { data: setupStatus } = useQuery({
    queryKey: ["setup-status"],
    queryFn: () => apiGet<SetupStatus>("/setup/status"),
  });

  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiGet<SettingsMap>("/settings"),
  });

  useEffect(() => {
    if (settings) {
      const v: Record<string, string> = {};
      for (const field of settingFields) {
        v[field.key] = settings[field.key] != null ? String(settings[field.key]) : "";
      }
      setValues(v);
    }
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiPut("/settings", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const handleSave = () => {
    const body: Record<string, unknown> = {};
    for (const field of settingFields) {
      const val = values[field.key]?.trim();
      // Only send non-masked values
      if (val && !val.includes("****")) {
        body[field.key] = val;
      } else if (!val) {
        body[field.key] = null;
      }
    }
    saveMutation.mutate(body);
  };

  const groups = [...new Set(settingFields.map((f) => f.group))];

  return (
    <div className="p-6 max-w-[800px] mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-medium text-foreground">Settings</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Integration keys and configuration</p>
      </div>

      {/* GitHub status */}
      {setupStatus && (
        <div className="bg-card border border-border rounded-md p-4 mb-6">
          <h2 className="label-uppercase mb-3">GITHUB CONNECTION</h2>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <span className="label-uppercase">STATUS</span>
              <p className={cn("text-xs mt-0.5", setupStatus.configured ? "text-success" : "text-warning")}>
                {setupStatus.configured ? "Connected" : "Not configured"}
              </p>
            </div>
            <div>
              <span className="label-uppercase">ORG</span>
              <p className="text-xs text-foreground mt-0.5">{setupStatus.org || "—"}</p>
            </div>
            <div>
              <span className="label-uppercase">PROJECT</span>
              <p className="text-xs text-foreground mt-0.5">{setupStatus.projectNumber || "—"}</p>
            </div>
          </div>
        </div>
      )}

      {/* Settings form */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-16 bg-card border border-border rounded-md animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((group) => (
            <div key={group}>
              <h2 className="label-uppercase mb-3">{group.toUpperCase()}</h2>
              <div className="space-y-3">
                {settingFields
                  .filter((f) => f.group === group)
                  .map((field) => (
                    <div key={field.key} className="bg-card border border-border rounded-md px-4 py-3">
                      <label className="text-xs text-foreground block mb-1.5">{field.label}</label>
                      <input
                        type={field.sensitive ? "password" : "text"}
                        value={values[field.key] || ""}
                        onChange={(e) =>
                          setValues((v) => ({ ...v, [field.key]: e.target.value }))
                        }
                        placeholder={field.placeholder}
                        className="w-full bg-background border border-border rounded px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                      />
                    </div>
                  ))}
              </div>
            </div>
          ))}

          <div className="flex items-center gap-3">
            <button
              onClick={handleSave}
              disabled={saveMutation.isPending}
              className="bg-primary text-primary-foreground px-4 py-2 rounded-md text-xs hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving..." : "Save Settings"}
            </button>
            {saved && (
              <span className="flex items-center gap-1 text-xs text-success">
                <Check size={12} /> Saved
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
