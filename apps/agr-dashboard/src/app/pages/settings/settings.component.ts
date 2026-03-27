import { Component, inject, ChangeDetectionStrategy, signal, OnInit } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiKeyService } from '../../services/api-key.service';
import { ComplianceService } from '../../services/compliance.service';
import { OrgService, OrgMe, SsoSettings, UsageSummary } from '../../services/org.service';
import { ClerkService } from '../../core/auth/clerk.service';

@Component({
  selector: 'agr-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DecimalPipe],
  template: `
    <div class="max-w-2xl mx-auto">
      <h1 class="text-2xl font-bold text-slate-100 mb-6">Settings</h1>

      <!-- Org Info -->
      @if (org()) {
        <div class="card mb-6">
          <h2 class="text-base font-semibold text-slate-100 mb-3">Organization</h2>
          <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt class="text-slate-400">Name</dt>
            <dd class="text-slate-100 font-medium">{{ org()!.name }}</dd>

            <dt class="text-slate-400">Plan</dt>
            <dd>
              <span class="px-2 py-0.5 rounded-full text-xs font-semibold uppercase
                           bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                {{ org()!.plan }}
              </span>
            </dd>

            <dt class="text-slate-400">Evaluations</dt>
            <dd class="text-slate-100">
              @if ((usage()?.eval_limit ?? org()!.eval_limit) === 0) {
                {{ (usage()?.total_evaluations ?? org()!.eval_count) | number }} / Unlimited
              } @else {
                {{ (usage()?.total_evaluations ?? org()!.eval_count) | number }} / {{ (usage()?.eval_limit ?? org()!.eval_limit) | number }}
                <span class="text-xs text-slate-500 ml-1">this week</span>
              }
            </dd>

            @if ((usage()?.eval_limit ?? org()!.eval_limit) > 0) {
              <dt class="text-slate-400">Usage</dt>
              <dd class="flex items-center gap-2">
                <div class="flex-1 h-1.5 rounded-full bg-slate-700 overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all"
                    [class]="usageBarClass()"
                    [style.width.%]="usagePct()"
                  ></div>
                </div>
                <span class="text-xs text-slate-400">{{ usagePct() }}%</span>
              </dd>

              <dt class="text-slate-400">Week resets</dt>
              <dd class="text-xs text-slate-400">{{ weekResetLabel() }}</dd>
            }

            <dt class="text-slate-400">Auth mode</dt>
            <dd class="text-slate-100">
              {{ org()!.auth_mode === 'sso_session' ? 'Enterprise SSO session' : 'Stored API key' }}
              @if (org()!.auth_expires_at) {
                <span class="text-xs text-slate-500 ml-1">expires {{ org()!.auth_expires_at }}</span>
              }
            </dd>
          </dl>

          @if (usage()?.warning_message) {
            <div class="mt-4 rounded-lg border px-3 py-2 text-sm"
                 [class]="usage()!.quota_state === 'exceeded'
                   ? 'border-red-500/30 bg-red-500/10 text-red-300'
                   : 'border-amber-500/30 bg-amber-500/10 text-amber-300'">
              {{ usage()!.warning_message }}
            </div>
          }

          @if (usage() && usage()!.per_agent.length > 0) {
            <div class="mt-4">
              <h3 class="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
                Top Agent Usage
              </h3>
              <div class="space-y-2">
                @for (entry of usage()!.per_agent.slice(0, 5); track entry.agent_id) {
                  <div class="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                    <div class="flex items-center justify-between gap-3">
                      <span class="font-mono text-xs text-slate-200">{{ entry.agent_id }}</span>
                      <span class="text-xs text-slate-400">{{ entry.total_evaluations | number }} evals</span>
                    </div>
                    <div class="mt-1 text-[11px] text-slate-500">{{ entry.share_pct }}% of org usage</div>
                  </div>
                }
              </div>
            </div>
          }
        </div>
      }

      <!-- Compliance Export -->
      <div class="card mb-6">
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 class="text-base font-semibold text-slate-100 mb-1">Compliance Report Export</h2>
            <p class="text-sm text-slate-400">
              Download an org-scoped compliance and audit report with policy violations, risk summary,
              remediation guidance, and audit trail coverage.
            </p>
            <p class="text-xs text-slate-500 mt-2">
              JSON export is supported directly. PDF requests currently fall back to JSON to avoid adding a heavy renderer.
            </p>
          </div>

          <button
            (click)="downloadComplianceExport()"
            [disabled]="exportingCompliance()"
            class="btn-primary"
          >
            {{ exportingCompliance() ? 'Preparing export…' : 'Export compliance JSON' }}
          </button>
        </div>

        @if (complianceExportError()) {
          <p class="text-xs text-red-400 mt-3">{{ complianceExportError() }}</p>
        }
      </div>

      <!-- SSO / SAML -->
      <div class="card mb-6">
        <h2 class="text-base font-semibold text-slate-100 mb-1">Enterprise SSO / SAML</h2>
        <p class="text-sm text-slate-400 mb-4">
          Configure how Clerk-managed SAML identities map into this AGR organization. The IdP connection
          still lives in your auth provider; AGR stores the org mapping, allowed domains, and default role.
        </p>

        @if (ssoError()) {
          <div class="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
            {{ ssoError() }}
          </div>
        }

        @if (ssoSaved()) {
          <div class="mb-3 rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-300">
            SSO settings saved.
          </div>
        }

        @if (org()?.role !== 'admin') {
          <p class="text-sm text-slate-500">
            Only admins can view and update SSO mapping settings for this organisation.
          </p>
        } @else {
          <div class="grid gap-3 md:grid-cols-2">
            <label class="text-sm text-slate-300">
              <span class="block text-xs text-slate-400 mb-1">Provider</span>
              <input [(ngModel)]="ssoProviderInput" class="input w-full" placeholder="Clerk SAML" />
            </label>

            <label class="text-sm text-slate-300">
              <span class="block text-xs text-slate-400 mb-1">Entity ID</span>
              <input [(ngModel)]="ssoEntityIdInput" class="input w-full" placeholder="urn:example:idp" />
            </label>

            <label class="text-sm text-slate-300 md:col-span-2">
              <span class="block text-xs text-slate-400 mb-1">Metadata URL</span>
              <input [(ngModel)]="ssoMetadataUrlInput" class="input w-full" placeholder="https://idp.example.com/metadata" />
            </label>

            <label class="text-sm text-slate-300 md:col-span-2">
              <span class="block text-xs text-slate-400 mb-1">Allowed email domains</span>
              <input [(ngModel)]="ssoDomainsInput" class="input w-full" placeholder="example.com, subsidiary.example.com" />
            </label>

            <label class="text-sm text-slate-300 md:col-span-2">
              <span class="block text-xs text-slate-400 mb-1">Metadata XML (optional)</span>
              <textarea [(ngModel)]="ssoMetadataXmlInput" class="input w-full min-h-[120px]" placeholder="<EntityDescriptor>…"></textarea>
            </label>
          </div>

          <div class="mt-4 flex flex-wrap items-center gap-4 text-sm text-slate-300">
            <label class="inline-flex items-center gap-2">
              <input type="checkbox" [(ngModel)]="ssoEnabled" />
              Enable SSO mapping
            </label>
            <label class="inline-flex items-center gap-2">
              <input type="checkbox" [(ngModel)]="ssoAutoJoin" />
              Auto-join matching identities
            </label>
            <label class="inline-flex items-center gap-2">
              <span class="text-xs text-slate-400">Default role</span>
              <select [(ngModel)]="ssoDefaultRole" class="input min-w-[140px]">
                <option value="viewer">viewer</option>
                <option value="operator">operator</option>
                <option value="admin">admin</option>
              </select>
            </label>
          </div>

          <div class="mt-4 flex items-center gap-3">
            <button (click)="saveSsoSettings()" [disabled]="savingSso()" class="btn-primary">
              {{ savingSso() ? 'Saving…' : 'Save SSO settings' }}
            </button>
            <span class="text-xs text-slate-500">
              Recommended setup: configure the SAML connection in Clerk, then add the same metadata and domains here for AGR org mapping.
            </span>
          </div>
        }
      </div>

      <!-- API Key -->
      <div class="card mb-6">
        <h2 class="text-base font-semibold text-slate-100 mb-1">API Key</h2>
        <p class="text-sm text-slate-400 mb-4">
          AGR stores either an org API key
          <code class="text-indigo-300 bg-slate-800 px-1 rounded">agr_sk_</code> or an SSO session token
          <code class="text-indigo-300 bg-slate-800 px-1 rounded">agr_usr_</code> in this browser to authenticate API requests.
        </p>

        @if (saved()) {
          <div class="mb-3 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/20">
            <p class="text-sm text-green-400">API key saved successfully.</p>
          </div>
        }

        @if (fetchSuccess()) {
          <div class="mb-3 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/20">
            <p class="text-sm text-green-400">API key retrieved automatically from your account.</p>
          </div>
        }

        @if (fetchError()) {
          <div class="mb-3 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <p class="text-sm text-amber-400">{{ fetchError() }}</p>
          </div>
        }

        @if (error()) {
          <div class="mb-3 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
            <p class="text-sm text-red-400">{{ error() }}</p>
          </div>
        }

        <!-- Auto-fetch button (shown when no key is set) -->
        @if (!hasKey() && !fetching()) {
          <button
            (click)="fetchFromClerk()"
            class="mb-4 w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg
                   bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium
                   transition-colors border border-indigo-500"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Fetch API Key Automatically
          </button>
        }

        @if (fetching()) {
          <div class="mb-4 flex items-center gap-2 px-3 py-2.5 rounded-lg bg-slate-800 border border-slate-700">
            <svg class="w-4 h-4 animate-spin text-indigo-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span class="text-sm text-slate-400">Fetching API key from your account…</span>
          </div>
        }

        <div class="space-y-3">
          <!-- Input + eye toggle -->
          <div class="relative">
            <input
              [type]="showKey() ? 'text' : 'password'"
              [(ngModel)]="keyInput"
              placeholder="agr_sk_… or agr_usr_…"
              class="input w-full font-mono pr-10"
              autocomplete="off"
            />
            <button
              type="button"
              (click)="showKey.set(!showKey())"
              class="absolute inset-y-0 right-0 flex items-center px-3 text-slate-500 hover:text-slate-200 transition-colors"
              [attr.aria-label]="showKey() ? 'Hide API key' : 'Show API key'"
            >
              @if (showKey()) {
                <!-- Eye-slash icon -->
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round"
                    d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7
                       a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243
                       M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29
                       m7.532 7.532l3.29 3.29M3 3l3.59 3.59
                       m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7
                       a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
              } @else {
                <!-- Eye icon -->
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round"
                    d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path stroke-linecap="round" stroke-linejoin="round"
                    d="M2.458 12C3.732 7.943 7.523 5 12 5
                       c4.478 0 8.268 2.943 9.542 7
                       -1.274 4.057-5.064 7-9.542 7
                       -4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              }
            </button>
          </div>

          <div class="flex items-center gap-3">
            <button (click)="save()" class="btn-primary">Save key</button>
            @if (hasKey()) {
              <button
                (click)="fetchFromClerk()"
                [disabled]="fetching()"
                class="px-3 py-1.5 text-sm text-indigo-400 border border-indigo-500/30
                       rounded-lg hover:bg-indigo-500/10 transition-colors disabled:opacity-50"
              >
                Refresh from Clerk
              </button>
              <button
                (click)="clear()"
                class="px-3 py-1.5 text-sm text-red-400 border border-red-500/30
                       rounded-lg hover:bg-red-500/10 transition-colors"
              >
                Remove key
              </button>
            }
          </div>
        </div>

        @if (hasKey()) {
          <div class="mt-4 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-green-400"></span>
            <span class="text-xs text-slate-400">API key configured</span>
          </div>
        }
      </div>

      <!-- About -->
      <div class="card">
        <h2 class="text-base font-semibold text-slate-100 mb-1">About</h2>
        <p class="text-sm text-slate-400">
          AGR Dashboard — Agentic Governance Runtime v0.1
        </p>
        <p class="text-xs text-slate-500 mt-2">
          Manage AI agent policies, approve pending tool calls, and view audit logs.
        </p>
      </div>
    </div>
  `,
})
export class SettingsComponent implements OnInit {
  private apiKey = inject(ApiKeyService);
  private orgSvc = inject(OrgService);
  private clerkSvc = inject(ClerkService);
  private complianceSvc = inject(ComplianceService);

  keyInput = this.apiKey.getKey() ?? '';
  readonly hasKey = this.apiKey.hasKey.bind(this.apiKey);
  readonly saved = signal(false);
  readonly error = signal('');
  readonly fetchError = signal('');
  readonly fetchSuccess = signal(false);
  readonly fetching = signal(false);
  readonly org = signal<OrgMe | null>(null);
  readonly usage = signal<UsageSummary | null>(null);
  readonly showKey = signal(false);
  readonly complianceExportError = signal('');
  readonly exportingCompliance = signal(false);
  readonly savingSso = signal(false);
  readonly ssoError = signal('');
  readonly ssoSaved = signal(false);
  readonly sso = signal<SsoSettings | null>(null);

  ssoEnabled = false;
  ssoAutoJoin = false;
  ssoProviderInput = '';
  ssoMetadataUrlInput = '';
  ssoMetadataXmlInput = '';
  ssoEntityIdInput = '';
  ssoDomainsInput = '';
  ssoDefaultRole: 'admin' | 'operator' | 'viewer' = 'viewer';

  ngOnInit(): void {
    if (this.hasKey()) {
      this.loadOrgContext();
    } else {
      // No key in storage — attempt auto-fetch so the user doesn't have to manually paste it
      this.fetchFromClerk();
    }
  }

  async fetchFromClerk(): Promise<void> {
    this.fetching.set(true);
    this.fetchError.set('');
    this.fetchSuccess.set(false);

    const result = await this.clerkSvc.fetchApiKey();

    this.fetching.set(false);

    if (result.ok) {
      this.keyInput = this.apiKey.getKey() ?? '';
      this.fetchSuccess.set(true);
      setTimeout(() => this.fetchSuccess.set(false), 4000);
      this.loadOrgContext();
      return;
    }

    const messages: Record<string, string> = {
      not_signed_in: 'You must be signed in to fetch your API key automatically.',
      clerk_not_configured:
        'Automatic key retrieval is not configured on this server. ' +
        'Copy your API key from the server and paste it below.',
      org_not_found:
        'Your account was not found yet — your registration may still be processing. ' +
        'Wait a moment and click "Fetch API Key Automatically" again.',
      access_denied:
        'Your SSO identity does not have an active AGR org membership yet. Ask an admin to review the SSO mapping.',
      ambiguous_org_mapping:
        'Your SSO identity matches multiple AGR organizations. Ask an admin to narrow the SSO domain or entity mapping.',
      error: 'Could not fetch API key automatically. Paste your key below.',
    };
    this.fetchError.set(messages[result.reason] ?? messages['error']);
  }

  usagePct(): number {
    const summary = this.usage();
    if (summary) return Math.min(100, summary.usage_pct);
    const o = this.org();
    if (!o || o.eval_limit === 0) return 0;
    return Math.min(100, Math.round((o.eval_count / o.eval_limit) * 100));
  }

  usageBarClass(): string {
    const pct = this.usagePct();
    if (pct >= 90) return 'bg-red-500';
    if (pct >= 70) return 'bg-amber-400';
    return 'bg-indigo-500';
  }

  weekResetLabel(): string {
    const o = this.org();
    if (!o?.eval_week_start) return 'Not started yet';
    const start = new Date(o.eval_week_start);
    const reset = new Date(start.getTime() + 7 * 24 * 60 * 60 * 1000);
    const diff = reset.getTime() - Date.now();
    if (diff <= 0) return 'Resetting now…';
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    return days > 0 ? `in ${days}d ${hours}h` : `in ${hours}h`;
  }

  save(): void {
    const trimmed = this.keyInput.trim();
    if (!trimmed.startsWith('agr_sk_') && !trimmed.startsWith('agr_usr_')) {
      this.error.set('Token must start with agr_sk_ or agr_usr_');
      return;
    }
    this.apiKey.setKey(trimmed);
    this.error.set('');
    this.saved.set(true);
    setTimeout(() => this.saved.set(false), 3000);
    this.loadOrgContext();
  }

  clear(): void {
    this.apiKey.clearKey();
    this.keyInput = '';
    this.saved.set(false);
    this.fetchSuccess.set(false);
    this.fetchError.set('');
    this.org.set(null);
    this.usage.set(null);
    this.sso.set(null);
    this.showKey.set(false);
  }

  saveSsoSettings(): void {
    this.savingSso.set(true);
    this.ssoError.set('');
    this.ssoSaved.set(false);
    this.orgSvc
      .updateSso({
        enabled: this.ssoEnabled,
        provider: this.ssoProviderInput.trim() || null,
        metadata_url: this.ssoMetadataUrlInput.trim() || null,
        metadata_xml: this.ssoMetadataXmlInput.trim() || null,
        entity_id: this.ssoEntityIdInput.trim() || null,
        domains: this.ssoDomainsInput
          .split(',')
          .map((item) => item.trim().toLowerCase())
          .filter(Boolean),
        default_role: this.ssoDefaultRole,
        auto_join: this.ssoAutoJoin,
      })
      .subscribe({
        next: (settings) => {
          this.savingSso.set(false);
          this.applySsoSettings(settings);
          this.ssoSaved.set(true);
          setTimeout(() => this.ssoSaved.set(false), 3000);
        },
        error: () => {
          this.savingSso.set(false);
          this.ssoError.set('Unable to save SSO settings right now.');
        },
      });
  }

  downloadComplianceExport(): void {
    this.exportingCompliance.set(true);
    this.complianceExportError.set('');
    this.complianceSvc.exportReport({ format: 'json', period_days: 30 }).subscribe({
      next: (blob) => {
        this.exportingCompliance.set(false);
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = 'agr-compliance-report.json';
        anchor.click();
        URL.revokeObjectURL(url);
      },
      error: () => {
        this.exportingCompliance.set(false);
        this.complianceExportError.set('Unable to export the compliance report.');
      },
    });
  }

  private loadOrgContext(): void {
    this.orgSvc.getMe().subscribe({ next: (o) => this.org.set(o) });
    this.orgSvc.getUsage().subscribe({
      next: (usage) => this.usage.set(usage),
      error: () => this.usage.set(null),
    });
    this.orgSvc.getSso().subscribe({
      next: (settings) => this.applySsoSettings(settings),
      error: (err) => {
        if (err?.status === 403) {
          this.ssoError.set('Only admins can view or update SSO settings.');
        } else {
          this.ssoError.set('SSO settings are not available right now.');
        }
      },
    });
  }

  private applySsoSettings(settings: SsoSettings): void {
    this.sso.set(settings);
    this.ssoEnabled = settings.enabled;
    this.ssoAutoJoin = settings.auto_join;
    this.ssoProviderInput = settings.provider ?? '';
    this.ssoMetadataUrlInput = settings.metadata_url ?? '';
    this.ssoMetadataXmlInput = settings.metadata_xml ?? '';
    this.ssoEntityIdInput = settings.entity_id ?? '';
    this.ssoDomainsInput = settings.domains.join(', ');
    this.ssoDefaultRole = settings.default_role;
    this.ssoError.set('');
  }
}
