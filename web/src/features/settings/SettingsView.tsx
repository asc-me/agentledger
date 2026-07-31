import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Github, HardDrive, KeyRound, Plug, Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import * as React from "react";

import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { AiProvidersPanel } from "@/features/settings/AiProvidersPanel";
import { McpInstall } from "@/features/settings/McpInstall";
import { SyncCredentialInstall } from "@/features/settings/SyncCredentialInstall";
import { SyncLinkPanel } from "@/features/settings/SyncLinkPanel";
import { useProjectCtx } from "@/features/ProjectContext";
import { copyText } from "@/lib/clipboard";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { errorDetail } from "@/lib/errors";
import { keys, useApiKeys, useMembers, usePlatform } from "@/lib/queries";
import type { PlatformConfig, Project } from "@/lib/types";

const TABS = ["AI Providers", "Integrations", "Sync / Link", "Project", "Members", "API Keys"] as const;
type Tab = (typeof TABS)[number];

export function SettingsView() {
  const [tab, setTab] = React.useState<Tab>("AI Providers");
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex-none border-b border-line px-5 py-4">
        <h1 className="text-[18px] font-semibold tracking-tight">Settings</h1>
        <p className="mt-0.5 text-[12.5px] text-muted">Providers, integrations, project config, members, and API keys.</p>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[200px_1fr]">
        <div className="flex flex-col gap-0.5 border-r border-line p-3">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded-[9px] px-3 py-2 text-left text-[13px] transition-colors",
                tab === t ? "bg-surface-3 text-fg" : "text-muted hover:bg-surface-3 hover:text-fg-2",
              )}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="min-h-0 overflow-y-auto p-6">
          {tab === "AI Providers" && <AiProvidersPanel />}
          {tab === "Integrations" && <IntegrationsPanel />}
          {tab === "Sync / Link" && <SyncLinkPanel />}
          {tab === "Project" && <ProjectPanel />}
          {tab === "Members" && <MembersPanel />}
          {tab === "API Keys" && <ApiKeysPanel />}
        </div>
      </div>
    </div>
  );
}

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="mb-6 max-w-2xl">
      <div className="text-[14px] font-semibold">{title}</div>
      {desc && <p className="mb-3 mt-0.5 text-[12.5px] text-muted">{desc}</p>}
      <div className={desc ? "" : "mt-3"}>{children}</div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-faint">{children}</div>;
}

function IntegrationsPanel() {
  const { data: cfg } = usePlatform();
  const qc = useQueryClient();
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const invalidate = () => qc.invalidateQueries({ queryKey: ["platform"] });
  const [ghAccount, setGhAccount] = React.useState("");
  const [ghRepo, setGhRepo] = React.useState("");
  const [drAccount, setDrAccount] = React.useState("");
  const [drFolder, setDrFolder] = React.useState("");
  const [copied, setCopied] = React.useState(false);
  const [syncing, setSyncing] = React.useState(false);
  const [syncReport, setSyncReport] = React.useState<Awaited<ReturnType<typeof api.gdriveSync>> | null>(null);
  async function runSync() {
    setSyncing(true);
    try {
      setSyncReport(await api.gdriveSync());
      qc.invalidateQueries({ queryKey: keys.prds });
    } finally {
      setSyncing(false);
    }
  }
  const [rateLimit, setRateLimit] = React.useState(20);
  const [sitekey, setSitekey] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [spamSaved, setSpamSaved] = React.useState(false);
  React.useEffect(() => {
    if (cfg) {
      setRateLimit(cfg.rate_limit_per_min);
      setSitekey(cfg.turnstile_sitekey);
    }
  }, [cfg?.project_id, cfg?.rate_limit_per_min, cfg?.turnstile_sitekey]); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveSpam() {
    const body: Partial<PlatformConfig> & { turnstile_secret?: string } = {
      rate_limit_per_min: rateLimit,
      turnstile_sitekey: sitekey,
    };
    if (secret) body.turnstile_secret = secret;
    await api.updatePlatform(body);
    setSecret("");
    invalidate();
    setSpamSaved(true);
    setTimeout(() => setSpamSaved(false), 1500);
  }

  if (!cfg) return null;

  return (
    <div className="max-w-2xl space-y-6">
      {/* GitHub */}
      <div className="rounded-[13px] border border-line-2 bg-surface-2 p-4">
        <div className="mb-3 flex items-center gap-2.5">
          <Github size={17} className="text-fg" />
          <div className="text-[14px] font-semibold">GitHub</div>
          <StatusPill connected={cfg.github_connected} />
        </div>
        {cfg.github_connected ? (
          <div className="space-y-3">
            <Row label="Account" value={cfg.github_account} />
            <Row label="Repository" value={cfg.github_repo} />
            <Row label="Scope" value={cfg.github_scope} />
            <Button variant="danger" size="sm" onClick={() => api.githubDisconnect().then(invalidate)}>
              Disconnect
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div><Label>Account / org</Label><Input value={ghAccount} onChange={(e) => setGhAccount(e.target.value)} placeholder="acme" /></div>
              <div><Label>Repository</Label><Input value={ghRepo} onChange={(e) => setGhRepo(e.target.value)} placeholder="acme/app" /></div>
            </div>
            <Button size="sm" disabled={!ghAccount || !ghRepo} onClick={() => api.githubConnect(ghAccount, ghRepo).then(invalidate)}>
              Connect
            </Button>
          </div>
        )}
        <div className="mt-4 border-t border-line pt-3">
          <Label>Inbound issues webhook</Label>
          <div className="flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-md border border-line-2 bg-surface px-2.5 py-1.5 font-mono text-[11px] text-muted-2">
              {origin}/api/public/github/webhook
            </code>
            <button
              className="rounded-md border border-line-2 bg-surface-3 p-1.5 text-muted hover:text-fg"
              onClick={() =>
                copyText(`${origin}/api/public/github/webhook`).then(
                  (ok) => ok && (setCopied(true), setTimeout(() => setCopied(false), 1500)),
                )
              }
            >
              {copied ? <Check size={13} className="text-accent" /> : <Copy size={13} />}
            </button>
          </div>
          <p className="mt-1.5 text-[11px] text-faint">
            Opened issues from the connected repo become tracker items <em>in this project</em>,
            each linked back to the GitHub issue.
          </p>
        </div>
      </div>

      {/* Google Drive */}
      <div className="rounded-[13px] border border-line-2 bg-surface-2 p-4">
        <div className="mb-3 flex items-center gap-2.5">
          <HardDrive size={17} className="text-fg" />
          <div className="text-[14px] font-semibold">Google Drive</div>
          <StatusPill connected={cfg.gdrive_connected} />
        </div>
        {cfg.gdrive_connected ? (
          <div className="space-y-3">
            <Row label="Account" value={cfg.gdrive_account} />
            <Row label="Folder" value={cfg.gdrive_folder} />
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={runSync} disabled={syncing}>
                <RefreshCw size={13} className={syncing ? "animate-spin" : ""} />
                {syncing ? "Syncing…" : "Sync now"}
              </Button>
              <Button variant="danger" size="sm" onClick={() => api.gdriveDisconnect().then(invalidate)}>
                Disconnect
              </Button>
            </div>
            {syncReport && (
              <div className="rounded-[11px] border border-line-2 bg-surface px-3 py-2.5 text-[12px]">
                <div className="mb-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-muted">
                  <span>↑ exported {syncReport.exported.length + syncReport.updated_file.length}</span>
                  <span>↓ imported {syncReport.imported.length + syncReport.updated_db.length}</span>
                  <span>= in sync {syncReport.in_sync}</span>
                  {syncReport.conflicts.length > 0 && (
                    <span className="text-st-blocked">⚠ conflicts {syncReport.conflicts.join(", ")}</span>
                  )}
                </div>
                <code className="block overflow-x-auto text-[10.5px] text-faint">{syncReport.prds_dir}</code>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div><Label>Account</Label><Input value={drAccount} onChange={(e) => setDrAccount(e.target.value)} placeholder="you@example.com" /></div>
              <div><Label>Folder</Label><Input value={drFolder} onChange={(e) => setDrFolder(e.target.value)} placeholder="/AgentLedger" /></div>
            </div>
            <Button size="sm" disabled={!drAccount} onClick={() => api.gdriveConnect(drAccount, drFolder).then(invalidate)}>
              Connect
            </Button>
          </div>
        )}
        <div className="mt-4 border-t border-line pt-3">
          <Label>How the folder is organized</Label>
          <p className="mb-2 text-[11px] text-faint">
            The folder is this project's root. PRDs two-way sync with the <code>PRDs/</code>
            subfolder — drop a <code>.md</code> there to import a draft; conflicts are flagged, not
            clobbered. The sync directory is a mounted volume; point it at a Google Drive Desktop
            folder to reach Drive.
          </p>
          <pre className="overflow-x-auto rounded-md border border-line-2 bg-surface px-2.5 py-2 font-mono text-[10.5px] leading-relaxed text-muted-2">{`<folder>/
  PRDs/         PRD markdown — drop a .md here to import a draft
  Digests/      generated progress digests
  Exports/      memory & item snapshots (JSON)
  Attachments/  feedback screenshots`}</pre>
          <p className="mt-1.5 text-[11px] text-faint">
            Files outside these subfolders are ignored; deleting a mirror never deletes the PRD.
          </p>
        </div>
      </div>

      {/* Public sharing */}
      <div className="rounded-[13px] border border-line-2 bg-surface-2 p-4">
        <div className="mb-1 flex items-center gap-2.5">
          <ShieldCheck size={17} className="text-fg" />
          <div className="text-[14px] font-semibold">Public sharing</div>
        </div>
        <p className="mb-3 text-[12px] text-muted">
          Off by default — no project data is public until you turn this on. When enabled, the
          read-only roadmap and feedback widget become reachable via an unguessable link.
        </p>
        <label className="mb-3 flex items-center gap-2 text-[12px] text-fg-2">
          <input
            type="checkbox"
            checked={cfg.public_share_enabled}
            onChange={async (e) => {
              await api.updatePlatform({ public_share_enabled: e.target.checked });
              invalidate();
            }}
            className="accent-accent"
          />
          Enable public roadmap + feedback widget for this project
        </label>
        {cfg.public_share_enabled && cfg.share_token && (
          <div className="flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-md border border-line-2 bg-surface-3 px-2 py-1.5 font-mono text-[11px] text-fg-2">
              {origin}/embed/roadmap?token={cfg.share_token}
            </code>
            <button
              className="rounded-md border border-line-2 bg-surface-3 p-1.5 text-muted hover:text-fg"
              onClick={() => copyText(`${origin}/embed/roadmap?token=${cfg.share_token}`).then((ok) => ok && (setCopied(true), setTimeout(() => setCopied(false), 1500)))}
              title="Copy public roadmap link"
            >
              {copied ? <Check size={13} className="text-accent" /> : <Copy size={13} />}
            </button>
          </div>
        )}
      </div>

      {/* Spam protection */}
      <div className="rounded-[13px] border border-line-2 bg-surface-2 p-4">
        <div className="mb-1 flex items-center gap-2.5">
          <ShieldCheck size={17} className="text-fg" />
          <div className="text-[14px] font-semibold">Spam protection</div>
        </div>
        <p className="mb-3 text-[12px] text-muted">
          Applies to the public feedback endpoints for this project. A honeypot is always on.
        </p>
        <div className="space-y-3">
          <div className="max-w-[200px]">
            <Label>Rate limit (submissions / minute / IP)</Label>
            <Input type="number" value={rateLimit} onChange={(e) => setRateLimit(Number(e.target.value) || 0)} />
          </div>
          <div>
            <Label>Cloudflare Turnstile site key <span className="text-faint-2">(optional)</span></Label>
            <Input value={sitekey} onChange={(e) => setSitekey(e.target.value)} placeholder="0x4AAAAAAA…" />
          </div>
          <div>
            <Label>
              Turnstile secret key{" "}
              {cfg.turnstile_secret_set ? (
                <span className="text-accent">· configured</span>
              ) : (
                <span className="text-faint-2">(optional; write-only)</span>
              )}
            </Label>
            <Input
              type="password"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              placeholder={cfg.turnstile_secret_set ? "•••••••• (leave blank to keep)" : "0x4AAAAAAA…"}
            />
          </div>
          <Button size="sm" onClick={saveSpam}>{spamSaved ? "Saved" : "Save spam settings"}</Button>
          <p className="text-[11px] text-faint">
            When a secret is set, submissions must pass Turnstile. Leave both blank for no captcha
            (default). The widget renders the challenge automatically.
          </p>
        </div>
      </div>
    </div>
  );
}

function ProjectPanel() {
  const { active } = useProjectCtx();
  const qc = useQueryClient();
  const [form, setForm] = React.useState<Partial<Project>>({});
  const [saved, setSaved] = React.useState(false);
  React.useEffect(() => {
    if (active) setForm({ name: active.name, description: active.description, share_global_memory: active.share_global_memory, auto_extract: active.auto_extract, mcp_enabled: active.mcp_enabled, memory_auto_reject: active.memory_auto_reject, memory_auto_accept: active.memory_auto_accept, memory_llm_judge: active.memory_llm_judge });
  }, [active?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!active) return null;

  async function save() {
    await api.updateProject(active!.id, form);
    qc.invalidateQueries({ queryKey: keys.projects });
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  const flags: { key: keyof Project; label: string; hint?: string; disabled?: boolean }[] = [
    { key: "share_global_memory", label: "Share global memory across projects" },
    { key: "auto_extract", label: "Auto-extract lessons on item completion" },
    { key: "mcp_enabled", label: "Expose MCP tools for this project" },
  ];

  // AL-227: memory auto-triage — the scorer acts on agent candidates on write.
  const triageFlags: { key: keyof Project; label: string; hint?: string; disabled?: boolean }[] = [
    { key: "memory_auto_reject", label: "Auto-reject duplicate & rejected-alike memories", hint: "On: near-duplicates and shards resembling ones you've rejected drop straight to rejected (kept, never surfaced — undoable)." },
    { key: "memory_auto_accept", label: "Auto-publish high-confidence memories", hint: "Off by default: strongly-corroborated lessons publish without review. Punches through the candidate boundary — every auto-publish is audited and undoable." },
    { key: "memory_llm_judge", label: "Use the LLM judge to assess memories", hint: "Needs a chat provider configured. The model rates each candidate's quality to refine the decisions above; falls back to similarity when no model is set." },
  ];

  return (
    <Section title="Project" desc="Configuration for the active project.">
      <div className="mb-3"><Label>Name</Label><Input value={form.name ?? ""} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className="max-w-sm" /></div>
      <div className="mb-4"><Label>Description</Label><Textarea rows={2} value={form.description ?? ""} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} /></div>
      <div className="mb-4 space-y-2">
        {flags.map((fl) => (
          <label key={fl.key} className="flex cursor-pointer items-center gap-2.5 text-[12.5px] text-fg-2">
            <input type="checkbox" className="accent-accent" checked={!!form[fl.key]} onChange={(e) => setForm((f) => ({ ...f, [fl.key]: e.target.checked }))} />
            {fl.label}
          </label>
        ))}
      </div>
      <div className="mb-4">
        <Label>Memory auto-triage</Label>
        <div className="mt-1 space-y-2.5">
          {triageFlags.map((fl) => (
            <label key={fl.key} className={cn("flex cursor-pointer gap-2.5 text-[12.5px] text-fg-2", fl.disabled && "cursor-not-allowed opacity-55")}>
              <input type="checkbox" className="accent-accent mt-0.5" disabled={fl.disabled} checked={!!form[fl.key]} onChange={(e) => setForm((f) => ({ ...f, [fl.key]: e.target.checked }))} />
              <span>
                {fl.label}
                {fl.hint && <span className="mt-0.5 block text-[11px] leading-snug text-faint">{fl.hint}</span>}
              </span>
            </label>
          ))}
        </div>
      </div>
      <Button size="sm" onClick={save}>{saved ? "Saved" : "Save project"}</Button>
    </Section>
  );
}

function MembersPanel() {
  const { activeId } = useProjectCtx();
  const { data: members = [] } = useMembers(activeId);
  return (
    <Section title="Members" desc="People with access to this project and their roles.">
      <div className="space-y-2">
        {members.map((m) => (
          <div key={m.user.id} className="flex items-center gap-3 rounded-[11px] border border-line-2 bg-surface-2 px-3 py-2.5">
            <Avatar initials={m.user.initials} color={m.user.avatar} size={30} />
            <div className="min-w-0 flex-1">
              <div className="text-[13px] text-fg-2">{m.user.name}</div>
              <div className="font-mono text-[10.5px] text-faint">@{m.user.handle}</div>
            </div>
            <span className="rounded-md border border-line-2 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-muted">{m.role}</span>
            <span className="w-12 text-right font-mono text-[10px] text-faint">{m.access}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

/** Agent keys talk to the MCP endpoint; sync credentials only push a code graph (AL-219 D4). */
type KeyKind = "agent" | "sync";

function ApiKeysPanel() {
  const { data: apiKeys = [] } = useApiKeys();
  const { active, projects } = useProjectCtx();
  const qc = useQueryClient();
  const [kind, setKind] = React.useState<KeyKind>("agent");
  const [name, setName] = React.useState("");
  const [global, setGlobal] = React.useState(false);
  const [expiryDays, setExpiryDays] = React.useState<number | null>(null);
  // A sync credential pins to one cloud project, so it gets its own explicit target rather
  // than riding the active project — a fleet mints one per project (D6).
  const [syncProject, setSyncProject] = React.useState<string>("");
  const [created, setCreated] = React.useState<{ plaintext: string; kind: KeyKind; projectId: string } | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [connectId, setConnectId] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Write access isn't in the Project shape; the backend rejects a sync key on a read-only
  // project with an honest 403, which surfaces in `error` below.
  const syncTarget = syncProject || active?.id || projects[0]?.id || "";

  const projectName = (id: string | null) =>
    id ? (projects.find((p) => p.id === id)?.name ?? id) : "All projects";

  async function create() {
    if (!name.trim()) return;
    setError(null);
    const isSync = kind === "sync";
    const projectId = isSync ? syncTarget : global ? null : active?.id ?? null;
    if (isSync && !projectId) {
      setError("Pick a project — a sync credential must target exactly one.");
      return;
    }
    try {
      const res = await api.createApiKey(name.trim(), projectId, expiryDays, isSync ? ["sync"] : undefined);
      setCreated({ plaintext: res.plaintext, kind, projectId: projectId ?? "" });
      setName("");
      qc.invalidateQueries({ queryKey: keys.apiKeys });
    } catch (e) {
      setError(errorDetail(e, "Could not create the key."));
    }
  }
  async function revoke(id: string) {
    await api.revokeApiKey(id);
    qc.invalidateQueries({ queryKey: keys.apiKeys });
  }

  return (
    <Section title="API keys" desc="Long-lived scoped keys for agents to authenticate to the MCP endpoint.">
      {created && (
        <div className="mb-4 rounded-[11px] border border-accent/40 bg-[rgba(198,242,78,0.06)] p-3">
          <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-accent">Copy now — shown once</div>
          <div className="flex items-center gap-2">
            <code className="flex-1 overflow-x-auto font-mono text-[12px] text-fg-2">{created.plaintext}</code>
            <button className="rounded-md border border-line-2 bg-surface-3 p-1.5 text-muted hover:text-fg"
              onClick={() => copyText(created.plaintext).then((ok) => ok && (setCopied(true), setTimeout(() => setCopied(false), 1500)))}>
              {copied ? <Check size={13} className="text-accent" /> : <Copy size={13} />}
            </button>
          </div>
          {created.kind === "sync" ? (
            <SyncCredentialInstall apiKey={created.plaintext} projectId={created.projectId} />
          ) : (
            <McpInstall apiKey={created.plaintext} />
          )}
        </div>
      )}
      <div className="mb-2 flex flex-wrap gap-1.5">
        {(
          [
            ["agent", "Agent key", "Talks to the MCP endpoint — read/write on items, memory, code."],
            ["sync", "Sync credential", "Pushes a code graph from a local instance into one project. Nothing else."],
          ] as const
        ).map(([id, label, desc]) => (
          <button
            key={id}
            onClick={() => {
              setKind(id);
              setError(null);
            }}
            title={desc}
            className={cn(
              "rounded-md border px-2.5 py-1 text-[11.5px] transition-colors",
              kind === id ? "border-accent/50 bg-surface-3 text-fg" : "border-line-2 text-muted hover:text-fg-2",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="mb-2 flex items-center gap-2">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={kind === "sync" ? "Key name (e.g. laptop — acme-core)" : "Key name (e.g. ci-agent)"}
          className="max-w-xs"
        />
        {kind === "sync" && (
          <select
            value={syncTarget}
            onChange={(e) => setSyncProject(e.target.value)}
            className="rounded-md border border-line-2 bg-surface-3 px-2 py-1.5 text-[12px] text-muted"
            aria-label="Sync target project"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
        <select
          value={expiryDays ?? ""}
          onChange={(e) => setExpiryDays(e.target.value ? Number(e.target.value) : null)}
          className="rounded-md border border-line-2 bg-surface-3 px-2 py-1.5 text-[12px] text-muted"
          aria-label="Key expiry"
        >
          <option value="">No expiry</option>
          <option value="30">Expires in 30 days</option>
          <option value="90">Expires in 90 days</option>
          <option value="365">Expires in 365 days</option>
        </select>
        <Button size="sm" onClick={create} disabled={!name.trim()}>
          <Plus size={14} />{kind === "sync" ? "Mint credential" : "Create key"}
        </Button>
      </div>
      {error && <p className="mb-2 text-[12px] text-st-blocked">{error}</p>}
      {kind === "sync" ? (
        <p className="mb-4 text-[12px] text-muted">
          Pinned to <span className="text-fg-2">{projectName(syncTarget)}</span> — a sync credential targets exactly one
          project, so a key distributed to a fleet can only ever push there.
        </p>
      ) : (
        <label className="mb-4 flex items-center gap-2 text-[12px] text-muted">
          <input type="checkbox" checked={global} onChange={(e) => setGlobal(e.target.checked)} className="accent-accent" />
          {global ? (
            <span>Global key — the agent passes <code className="font-mono text-[11px]">project_id</code> per call.</span>
          ) : (
            <span>Scoped to <span className="text-fg-2">{active?.name ?? "the active project"}</span> — check to make it global.</span>
          )}
        </label>
      )}
      <div className="space-y-2">
        {apiKeys.map((k) => (
          <div key={k.id} className="rounded-[11px] border border-line-2 bg-surface-2">
            <div className="flex items-center gap-3 px-3 py-2.5">
              <KeyRound size={14} className="text-muted" />
              <span className="text-[13px] text-fg-2">{k.name}</span>
              <code className="font-mono text-[11px] text-faint">{k.prefix}…</code>
              {k.scopes?.includes("sync") && (
                <span className="rounded border border-accent/40 px-1.5 py-px font-mono text-[9.5px] uppercase tracking-wide text-accent">
                  sync
                </span>
              )}
              <span
                className={cn(
                  "rounded border px-1.5 py-px font-mono text-[9.5px] uppercase tracking-wide",
                  k.project_id
                    ? "border-line-2 text-muted"
                    : "border-[rgba(167,139,250,0.3)] text-purple-2",
                )}
              >
                {projectName(k.project_id)}
              </span>
              {k.expires_at && (
                <span
                  className={cn(
                    "font-mono text-[9.5px] uppercase tracking-wide",
                    new Date(k.expires_at) <= new Date() ? "text-st-blocked" : "text-faint-2",
                  )}
                  title={`Expires ${new Date(k.expires_at).toLocaleDateString()}`}
                >
                  {new Date(k.expires_at) <= new Date() ? "expired" : `expires ${new Date(k.expires_at).toLocaleDateString()}`}
                </span>
              )}
              <span className="ml-auto font-mono text-[10px] text-faint-2">{k.last_used ? "used" : "never used"}</span>
              {/* Sync credentials never touch the MCP endpoint, so the MCP install snippet
                  would be misleading for them — the link hand-off is shown at mint time. */}
              {!k.scopes?.includes("sync") && (
                <button
                  className={cn("hover:text-fg", connectId === k.id ? "text-accent" : "text-faint")}
                  onClick={() => setConnectId(connectId === k.id ? null : k.id)}
                  title="Connect an agent (MCP setup)"
                >
                  <Plug size={14} />
                </button>
              )}
              <button className="text-faint hover:text-st-blocked" onClick={() => revoke(k.id)} title="Revoke">
                <Trash2 size={14} />
              </button>
            </div>
            {connectId === k.id && (
              <div className="border-t border-line px-3 pb-3">
                <McpInstall apiKey="<YOUR_API_KEY>" keyPrefix={k.prefix} />
              </div>
            )}
          </div>
        ))}
        {apiKeys.length === 0 && <p className="text-[12.5px] text-faint">No keys yet.</p>}
      </div>
    </Section>
  );
}

function StatusPill({ connected }: { connected: boolean }) {
  return (
    <span
      className={cn(
        "ml-auto flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide",
        connected ? "border-[#1c2620] bg-[rgba(95,208,122,0.06)] text-st-done" : "border-line-2 text-faint",
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", connected ? "bg-st-done" : "bg-faint")} />
      {connected ? "connected" : "not connected"}
    </span>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 text-[12.5px]">
      <span className="w-24 flex-none font-mono text-[10px] uppercase tracking-wide text-faint">{label}</span>
      <span className="text-fg-2">{value}</span>
    </div>
  );
}
