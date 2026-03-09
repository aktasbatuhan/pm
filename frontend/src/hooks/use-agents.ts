import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";
import type { SubAgent, Escalation, Kpi, SynthesisRun } from "@/types/agents";
import type { Action } from "@/types/api";

export function useSubAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => apiGet<{ agents: SubAgent[] }>("/agents").then((r) => r.agents),
    refetchInterval: 30_000,
  });
}

export function useEscalations(status?: string) {
  return useQuery({
    queryKey: ["escalations", status],
    queryFn: () =>
      apiGet<{ escalations: Escalation[] }>(
        `/agents/escalations${status ? `?status=${status}` : ""}`
      ).then((r) => r.escalations),
    refetchInterval: 30_000,
  });
}

export function useKpis() {
  return useQuery({
    queryKey: ["kpis"],
    queryFn: () => apiGet<{ kpis: Kpi[] }>("/agents/kpis").then((r) => r.kpis),
    refetchInterval: 30_000,
  });
}

export function useSynthesisRuns(limit = 5) {
  return useQuery({
    queryKey: ["synthesis", limit],
    queryFn: () =>
      apiGet<{ runs: SynthesisRun[] }>(`/agents/synthesis?limit=${limit}`).then(
        (r) => r.runs
      ),
    refetchInterval: 60_000,
  });
}

export function useActions(status?: string) {
  return useQuery({
    queryKey: ["actions", status],
    queryFn: () =>
      apiGet<{ actions: Action[] }>(
        `/actions${status ? `?status=${status}` : ""}`
      ).then((r) => r.actions),
    refetchInterval: 15_000,
  });
}

export function useApproveAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost(`/actions/${id}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["actions"] }),
  });
}

export function useRejectAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost(`/actions/${id}/reject`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["actions"] }),
  });
}
