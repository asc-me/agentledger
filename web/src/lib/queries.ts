import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type { Item, RequestItem } from "./types";

export const keys = {
  me: ["me"] as const,
  projects: ["projects"] as const,
  items: ["items"] as const,
  shards: ["shards"] as const,
  requests: ["requests"] as const,
  apiKeys: ["api-keys"] as const,
  prds: ["prds"] as const,
  prd: (id: string) => ["prd", id] as const,
  prdVersions: (id: string) => ["prd-versions", id] as const,
};

export function usePrds(projectId?: string) {
  return useQuery({ queryKey: [...keys.prds, projectId], queryFn: () => api.prds(projectId) });
}

export function usePrd(id: string) {
  return useQuery({ queryKey: keys.prd(id), queryFn: () => api.prd(id), enabled: !!id });
}

export function usePrdVersions(id: string) {
  return useQuery({ queryKey: keys.prdVersions(id), queryFn: () => api.prdVersions(id), enabled: !!id });
}

export function useDashboard(projectId?: string) {
  return useQuery({ queryKey: ["dashboard", projectId], queryFn: () => api.dashboard(projectId) });
}

export function useRoadmap(projectId?: string) {
  return useQuery({ queryKey: ["roadmap", projectId], queryFn: () => api.roadmap(projectId) });
}

export function useLinks(projectId?: string) {
  return useQuery({ queryKey: ["links", projectId], queryFn: () => api.links(projectId) });
}

export function useMcpTools() {
  return useQuery({ queryKey: ["mcp-tools"], queryFn: () => api.mcpTools() });
}

export function useEvents(projectId?: string) {
  return useQuery({ queryKey: ["events", projectId], queryFn: () => api.events(projectId) });
}

export function useCodeMap(projectId?: string) {
  return useQuery({ queryKey: ["code-map", projectId], queryFn: () => api.codeMap(projectId) });
}

export function usePlatform() {
  return useQuery({ queryKey: ["platform"], queryFn: () => api.platform() });
}

export function useMembers(projectId: string) {
  return useQuery({ queryKey: ["members", projectId], queryFn: () => api.members(projectId), enabled: !!projectId });
}

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: api.me });
}

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: () => api.projects() });
}

export function useItems(projectId?: string) {
  return useQuery({ queryKey: [...keys.items, projectId], queryFn: () => api.items(projectId) });
}

export function useUpdateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Item> }) => api.updateItem(id, body),
    onMutate: async ({ id, body }) => {
      await qc.cancelQueries({ queryKey: keys.items });
      const prev = qc.getQueriesData<Item[]>({ queryKey: keys.items });
      qc.setQueriesData<Item[]>({ queryKey: keys.items }, (old) =>
        old?.map((it) => (it.id === id ? { ...it, ...body } : it)),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev?.forEach(([key, data]) => qc.setQueryData(key, data)),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.items }),
  });
}

export function useCreateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Item>) => api.createItem(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.items }),
  });
}

export function useReorderItems() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orderedIds: string[]) => api.reorderItems(orderedIds),
    onMutate: async (orderedIds) => {
      await qc.cancelQueries({ queryKey: keys.items });
      const prev = qc.getQueriesData<Item[]>({ queryKey: keys.items });
      qc.setQueriesData<Item[]>({ queryKey: keys.items }, (old) => {
        if (!old) return old;
        const map = new Map(old.map((i) => [i.id, i]));
        return orderedIds.map((id, idx) => ({ ...map.get(id)!, sort_order: idx }));
      });
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev?.forEach(([key, data]) => qc.setQueryData(key, data)),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.items }),
  });
}

export function useShards(projectId?: string) {
  return useQuery({ queryKey: [...keys.shards, projectId], queryFn: () => api.shards(projectId) });
}

export function useAddShard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { text: string; scope?: string }) => api.addShard(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.shards }),
  });
}

export function useCandidateShards(projectId?: string) {
  return useQuery({
    queryKey: ["shard-candidates", projectId],
    queryFn: () => api.candidateShards(projectId),
  });
}

export function useCandidateClusters(projectId?: string) {
  return useQuery({
    queryKey: ["shard-clusters", projectId],
    queryFn: () => api.candidateClusters(projectId),
  });
}

function invalidateReview(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["shard-candidates"] });
  qc.invalidateQueries({ queryKey: ["shard-clusters"] });
  qc.invalidateQueries({ queryKey: keys.shards });
}

export function useReviewShard() {
  const qc = useQueryClient();
  const invalidate = () => invalidateReview(qc);
  return {
    publish: useMutation({ mutationFn: (id: string) => api.publishShard(id), onSuccess: invalidate }),
    reject: useMutation({ mutationFn: (id: string) => api.rejectShard(id), onSuccess: invalidate }),
  };
}

export function usePromoteCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { publishId: string; rejectIds: string[] }) =>
      api.promoteCluster(v.publishId, v.rejectIds),
    onSuccess: () => invalidateReview(qc),
  });
}

export function useRequests(projectId?: string) {
  return useQuery({ queryKey: [...keys.requests, projectId], queryFn: () => api.requests(projectId) });
}

export function useVoteRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, delta }: { id: string; delta: number }) => api.voteRequest(id, delta),
    onMutate: async ({ id, delta }) => {
      await qc.cancelQueries({ queryKey: keys.requests });
      const prev = qc.getQueriesData<RequestItem[]>({ queryKey: keys.requests });
      qc.setQueriesData<RequestItem[]>({ queryKey: keys.requests }, (old) =>
        old?.map((r) => (r.id === id ? { ...r, votes: Math.max(0, r.votes + delta) } : r)),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev?.forEach(([key, data]) => qc.setQueryData(key, data)),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.requests }),
  });
}

export function useLinkRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, itemId }: { id: string; itemId: string | null }) =>
      api.linkRequest(id, itemId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.requests }),
  });
}

export function useApiKeys() {
  return useQuery({ queryKey: keys.apiKeys, queryFn: () => api.apiKeys() });
}
