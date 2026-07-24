import { Check, Copy, Mail, ShieldCheck, X } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useAdminCreateInvite,
  useAdminDecideOrgRequest,
  useAdminInvites,
  useAdminOrgRequests,
  useAdminOrgs,
  useAdminRevokeInvite,
  useAdminUsers,
  useIsPlatformAdmin,
  useSetOrgPlan,
} from "@/lib/queries";
import type { AdminOrg, Invite, OrgRequest } from "@/lib/types";

const PLANS = ["free", "pro", "team", "enterprise"];

/** Server message out of an ApiError (body is a JSON `{detail}` envelope). */
function errorDetail(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "message" in err && typeof err.message === "string") {
    try {
      const parsed = JSON.parse(err.message);
      if (parsed && typeof parsed.detail === "string") return parsed.detail;
    } catch {
      /* not JSON */
    }
    if (err.message) return err.message;
  }
  return fallback;
}

/**
 * Operator console (AL-94) — run the beta without curl or DB access.
 *
 * Deliberately **metadata only**: orgs, plans, usage, invites, requests, and identity
 * for support lookups. No tenant content (items, memory, PRDs) is reachable here, which
 * is what keeps the Phase 6 cross-tenant isolation guarantee honest. The whole surface
 * 404s for anyone who isn't a platform admin on a hosted deployment.
 */
export function AdminView() {
  const { data: admin, isLoading, isError } = useIsPlatformAdmin();
  const ok = !!admin?.is_platform_admin;

  if (isLoading) {
    return <div className="p-8 font-mono text-[12px] text-faint">loading…</div>;
  }
  if (isError || !ok) {
    return (
      <div className="p-8 text-[13px] text-muted">
        This area is not available.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[880px] px-6 py-8">
      <header className="mb-6 flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-[9px] bg-[rgba(198,242,78,0.12)]">
          <ShieldCheck size={17} className="text-accent" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-[17px] font-semibold tracking-tight">Operator console</h1>
          <div className="font-mono text-[10px] uppercase tracking-wide text-faint">
            {admin.email} · metadata only
          </div>
        </div>
      </header>

      <OrgRequestsSection />
      <InvitesSection />
      <OrgsSection />
      <UsersSection />
    </div>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-2.5 font-mono text-[11px] uppercase tracking-wide text-faint">
        {title}
        {count != null && <span className="ml-1.5 text-faint-2">({count})</span>}
      </h2>
      {children}
    </section>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="overflow-hidden rounded-[12px] border border-line">{children}</div>;
}

function Row({ first, children }: { first: boolean; children: React.ReactNode }) {
  return (
    <div className={`flex items-center gap-3 px-4 py-3 ${first ? "" : "border-t border-line"}`}>
      {children}
    </div>
  );
}

// ── Additional-org requests ────────────────────────────────────────────────
function OrgRequestsSection() {
  const { data: requests = [] } = useAdminOrgRequests();
  return (
    <Section title="Additional-org requests" count={requests.length}>
      {requests.length === 0 ? (
        <p className="text-[12.5px] text-muted">No pending requests.</p>
      ) : (
        <Card>
          {requests.map((r, i) => (
            <OrgRequestRow key={r.id} req={r} first={i === 0} />
          ))}
        </Card>
      )}
    </Section>
  );
}

function OrgRequestRow({ req, first }: { req: OrgRequest; first: boolean }) {
  const decide = useAdminDecideOrgRequest();
  return (
    <Row first={first}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px]">{req.company || req.user_id}</div>
        <div className="truncate text-[11.5px] text-muted">{req.reason || "no reason given"}</div>
      </div>
      <Button
        size="sm"
        disabled={decide.isPending}
        onClick={() => decide.mutate({ id: req.id, approve: true })}
      >
        Approve
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={decide.isPending}
        onClick={() => decide.mutate({ id: req.id, approve: false })}
      >
        Deny
      </Button>
    </Row>
  );
}

// ── Platform invites ───────────────────────────────────────────────────────
function InvitesSection() {
  const { data: invites = [] } = useAdminInvites();
  return (
    <Section title="Platform invites" count={invites.length}>
      <InviteForm />
      {invites.length === 0 ? (
        <p className="text-[12.5px] text-muted">No pending invitations.</p>
      ) : (
        <Card>
          {invites.map((inv, i) => (
            <InviteRow key={inv.id} invite={inv} first={i === 0} />
          ))}
        </Card>
      )}
    </Section>
  );
}

function InviteForm() {
  const createInvite = useAdminCreateInvite();
  const [email, setEmail] = React.useState("");
  const [plan, setPlan] = React.useState("");
  const [error, setError] = React.useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setError("");
    try {
      await createInvite.mutateAsync({ email: email.trim(), plan: plan || null });
      setEmail("");
    } catch (err) {
      setError(errorDetail(err, "Could not send the invitation."));
    }
  }

  return (
    <form onSubmit={submit} className="mb-4 flex flex-wrap items-center gap-2">
      <div className="relative min-w-[220px] flex-1">
        <Mail size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
        <Input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="newcustomer@company.com"
          className="pl-8"
        />
      </div>
      <select
        value={plan}
        onChange={(e) => setPlan(e.target.value)}
        className="h-9 rounded-[8px] border border-line-2 bg-surface-2 px-2 text-[12px]"
        title="Plan to pre-assign to the org they found"
      >
        <option value="">default plan</option>
        {PLANS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      <Button type="submit" disabled={createInvite.isPending || !email.trim()}>
        {createInvite.isPending ? "Sending…" : "Invite"}
      </Button>
      {error && <span className="w-full text-[11px] text-st-blocked">{error}</span>}
    </form>
  );
}

function InviteRow({ invite, first }: { invite: Invite; first: boolean }) {
  const revoke = useAdminRevokeInvite();
  const [copied, setCopied] = React.useState(false);

  function copyLink() {
    navigator.clipboard?.writeText(invite.accept_url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <Row first={first}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px]">{invite.email}</div>
        <div className="font-mono text-[10px] uppercase tracking-wide text-faint">
          {invite.plan ? `plan: ${invite.plan}` : "default plan"}
        </div>
      </div>
      <button
        onClick={copyLink}
        title="Copy invite link"
        className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted hover:bg-surface-3 hover:text-fg"
      >
        {copied ? <Check size={13} className="text-accent" /> : <Copy size={13} />}
        {copied ? "Copied" : "Link"}
      </button>
      <button
        onClick={() => revoke.mutate(invite.id)}
        disabled={revoke.isPending}
        title="Revoke invitation"
        className="rounded-md p-1 text-faint hover:bg-surface-3 hover:text-st-blocked"
      >
        <X size={14} />
      </button>
    </Row>
  );
}

// ── Orgs ───────────────────────────────────────────────────────────────────
function OrgsSection() {
  const { data: orgs = [] } = useAdminOrgs();
  return (
    <Section title="Organizations" count={orgs.length}>
      {orgs.length === 0 ? (
        <p className="text-[12.5px] text-muted">No organizations yet.</p>
      ) : (
        <Card>
          {orgs.map((o, i) => (
            <OrgRow key={o.id} org={o} first={i === 0} />
          ))}
        </Card>
      )}
    </Section>
  );
}

function OrgRow({ org, first }: { org: AdminOrg; first: boolean }) {
  const setPlan = useSetOrgPlan();
  const u = org.usage;
  const l = org.limits;
  return (
    <Row first={first}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium">{org.name}</div>
        <div className="truncate font-mono text-[11px] text-faint">
          {org.owner_email ?? "no owner"}
        </div>
        <div className="mt-1 font-mono text-[10.5px] text-faint-2">
          {u.projects}/{l.max_projects} proj · {u.seats}/{l.max_seats} seats ·{" "}
          {u.shards.toLocaleString()}/{l.max_shards.toLocaleString()} shards ·{" "}
          {u.calls_this_month.toLocaleString()}/{l.max_calls_per_month.toLocaleString()} calls
        </div>
      </div>
      <select
        value={org.plan}
        disabled={setPlan.isPending}
        onChange={(e) => setPlan.mutate({ orgId: org.id, plan: e.target.value })}
        className="h-8 rounded-[8px] border border-line-2 bg-surface-2 px-2 text-[12px]"
        title="Assign plan"
      >
        {PLANS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
    </Row>
  );
}

// ── Users ──────────────────────────────────────────────────────────────────
function UsersSection() {
  const { data: users = [] } = useAdminUsers();
  return (
    <Section title="Users" count={users.length}>
      <Card>
        {users.map((u, i) => (
          <Row key={u.id} first={i === 0}>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px]">{u.name}</div>
              <div className="truncate font-mono text-[11px] text-faint">{u.email}</div>
            </div>
            <span className="rounded-md bg-surface-4 px-2 py-0.5 font-mono text-[10px] text-muted">
              {u.org_count} org{u.org_count === 1 ? "" : "s"}
            </span>
          </Row>
        ))}
      </Card>
    </Section>
  );
}
