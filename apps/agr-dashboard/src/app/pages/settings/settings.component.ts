import { Component, inject, ChangeDetectionStrategy, signal, OnInit } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiKeyService } from '../../services/api-key.service';
import { ComplianceService } from '../../services/compliance.service';
import {
  OrgApiKey,
  OrgApiKeyCreateResponse,
  OrgMe,
  OrgRiskConfig,
  OrgService,
  OrgSettings,
  SsoSettings,
  UsageSummary,
} from '../../services/org.service';
import { ClerkService } from '../../core/auth/clerk.service';

const AVAILABLE_API_KEY_SCOPES = [
  'evaluate:write',
  'policies:read',
  'policies:write',
  'approvals:read',
  'approvals:write',
  'agents:read',
  'agents:write',
  'audit:read',
  'webhooks:read',
  'webhooks:write',
  'compliance:read',
  'compliance:write',
  'org:admin',
  'copilot:read',
  'copilot:write',
] as const;

type AvailableApiKeyScope = (typeof AVAILABLE_API_KEY_SCOPES)[number];

interface RiskConfigFormModel {
  weight_action_severity: number;
  weight_context_signals: number;
  weight_rate_pattern: number;
  weight_agent_trust: number;
  weight_amount_scale: number;
  threshold_allow_max: number;
  threshold_approval_max: number;
}

function defaultRiskConfigForm(): RiskConfigFormModel {
  return {
    weight_action_severity: 0.3,
    weight_context_signals: 0.2,
    weight_rate_pattern: 0.2,
    weight_agent_trust: 0.15,
    weight_amount_scale: 0.15,
    threshold_allow_max: 40,
    threshold_approval_max: 70,
  };
}

@Component({
  selector: 'agr-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DecimalPipe],
  template: `
	    <div class="max-w-5xl mx-auto">
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

      <div class="card mb-6">
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 class="text-base font-semibold text-slate-100 mb-1">Scoped API Keys</h2>
            <p class="text-sm text-slate-400">
              Create org API keys with only the scopes each integration needs. New keys default to the full scope set.
            </p>
          </div>
          <span class="rounded-full border border-slate-700 px-2 py-1 text-[11px] uppercase tracking-wide text-slate-400">
            Admin only
          </span>
        </div>

        @if (createdOrgApiKey()) {
          <div class="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3">
            <p class="text-sm font-medium text-emerald-300">New key created</p>
            <p class="mt-2 font-mono text-xs text-emerald-100 break-all">{{ createdOrgApiKey()!.key }}</p>
            <p class="mt-2 text-xs text-emerald-200/80">Store this key now. AGR only shows the raw value once.</p>
          </div>
        }

        @if (orgApiKeysError()) {
          <div class="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {{ orgApiKeysError() }}
          </div>
        }

        @if (org()?.role !== 'admin') {
          <p class="mt-4 text-sm text-slate-500">Only admins can create, view, or revoke scoped org API keys.</p>
        } @else {
          <div class="mt-4 grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <div class="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <h3 class="text-sm font-semibold text-slate-100">Create key</h3>
              <label class="mt-4 block text-sm text-slate-300">
                <span class="mb-1 block text-xs text-slate-400">Display name</span>
                <input
                  [(ngModel)]="orgApiKeyNameInput"
                  class="input w-full"
                  placeholder="CI deploy token"
                />
              </label>

              <div class="mt-4">
                <div class="flex items-center justify-between gap-3">
                  <span class="text-xs font-semibold uppercase tracking-wide text-slate-400">Scopes</span>
                  <span class="text-xs text-slate-500">{{ selectedOrgApiKeyScopes.length }}/{{ availableApiKeyScopes.length }} selected</span>
                </div>
                <div class="mt-3 grid gap-2 sm:grid-cols-2">
                  @for (scope of availableApiKeyScopes; track scope) {
                    <label class="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-sm text-slate-300">
                      <input
                        type="checkbox"
                        [checked]="selectedOrgApiKeyScopes.includes(scope)"
                        (change)="toggleOrgApiKeyScope(scope, $any($event.target).checked)"
                      />
                      <span class="font-mono text-xs">{{ scope }}</span>
                    </label>
                  }
                </div>
              </div>

              <div class="mt-4 flex items-center gap-3">
                <button
                  (click)="createOrgApiKey()"
                  [disabled]="creatingOrgApiKey()"
                  class="btn-primary"
                >
                  {{ creatingOrgApiKey() ? 'Creating…' : 'Create scoped key' }}
                </button>
                <button
                  (click)="resetOrgApiKeyScopes()"
                  type="button"
                  class="px-3 py-1.5 text-sm text-slate-400 transition-colors hover:text-slate-200"
                >
                  Select all
                </button>
              </div>
            </div>

            <div class="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <div class="flex items-center justify-between gap-3">
                <h3 class="text-sm font-semibold text-slate-100">Issued keys</h3>
                @if (orgApiKeysLoading()) {
                  <span class="text-xs text-slate-500">Refreshing…</span>
                }
              </div>

              @if (!orgApiKeys().length && !orgApiKeysLoading()) {
                <p class="mt-4 text-sm text-slate-500">No scoped keys have been created yet.</p>
              } @else {
                <div class="mt-4 space-y-3">
                  @for (key of orgApiKeys(); track key.id) {
                    <article class="rounded-lg border border-slate-800 bg-slate-900/70 px-4 py-3">
                      <div class="flex items-start justify-between gap-4">
                        <div>
                          <div class="flex flex-wrap items-center gap-2">
                            <span class="text-sm font-semibold text-slate-100">{{ key.name }}</span>
                            <span class="rounded-full border border-slate-700 px-2 py-0.5 font-mono text-[11px] text-slate-400">
                              {{ key.key_prefix }}
                            </span>
                            @if (key.revoked) {
                              <span class="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] text-red-300">
                                revoked
                              </span>
                            }
                          </div>
                          <div class="mt-2 flex flex-wrap gap-2">
                            @for (scope of key.scopes; track scope) {
                              <span class="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[11px] font-mono text-indigo-300">
                                {{ scope }}
                              </span>
                            }
                          </div>
                          <div class="mt-3 text-xs text-slate-500">
                            Created by {{ key.created_by }} · Last used {{ key.last_used_at ?? 'never' }}
                          </div>
                        </div>
                        <button
                          (click)="revokeOrgApiKey(key.id)"
                          [disabled]="key.revoked || revokingOrgApiKeyIds()[key.id]"
                          class="rounded-lg border border-red-500/30 px-3 py-1.5 text-sm text-red-300 transition-colors hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {{ revokingOrgApiKeyIds()[key.id] ? 'Revoking…' : 'Revoke' }}
                        </button>
                      </div>
                    </article>
                  }
                </div>
              }
            </div>
          </div>
        }
      </div>

      <div class="card mb-6">
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 class="text-base font-semibold text-slate-100 mb-1">Risk Configuration</h2>
            <p class="text-sm text-slate-400">
              Tune the per-org risk weights and thresholds the backend uses when Cedar allows a request but risk scoring may escalate it.
            </p>
          </div>
          <span class="rounded-full border border-slate-700 px-2 py-1 text-[11px] uppercase tracking-wide text-slate-400">
            Admin only
          </span>
        </div>

        @if (riskConfigError()) {
          <div class="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {{ riskConfigError() }}
          </div>
        }

        @if (riskConfigSaved()) {
          <div class="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            Risk configuration saved.
          </div>
        }

        @if (org()?.role !== 'admin') {
          <p class="mt-4 text-sm text-slate-500">
            Risk tuning is visible to admins only. Non-admins continue using the org defaults set on the backend.
          </p>
        } @else {
          <div class="mt-4 grid gap-4 md:grid-cols-2">
            <label class="text-sm text-slate-300">
              <span class="mb-1 block text-xs text-slate-400">Action severity weight</span>
              <input [(ngModel)]="riskConfigForm.weight_action_severity" type="number" min="0" max="1" step="0.01" class="input w-full" />
            </label>
            <label class="text-sm text-slate-300">
              <span class="mb-1 block text-xs text-slate-400">Context signals weight</span>
              <input [(ngModel)]="riskConfigForm.weight_context_signals" type="number" min="0" max="1" step="0.01" class="input w-full" />
            </label>
            <label class="text-sm text-slate-300">
              <span class="mb-1 block text-xs text-slate-400">Rate pattern weight</span>
              <input [(ngModel)]="riskConfigForm.weight_rate_pattern" type="number" min="0" max="1" step="0.01" class="input w-full" />
            </label>
            <label class="text-sm text-slate-300">
              <span class="mb-1 block text-xs text-slate-400">Agent trust weight</span>
              <input [(ngModel)]="riskConfigForm.weight_agent_trust" type="number" min="0" max="1" step="0.01" class="input w-full" />
            </label>
            <label class="text-sm text-slate-300">
              <span class="mb-1 block text-xs text-slate-400">Amount scale weight</span>
              <input [(ngModel)]="riskConfigForm.weight_amount_scale" type="number" min="0" max="1" step="0.01" class="input w-full" />
            </label>
            <label class="text-sm text-slate-300">
              <span class="mb-1 block text-xs text-slate-400">Allow max threshold</span>
              <input [(ngModel)]="riskConfigForm.threshold_allow_max" type="number" min="0" max="100" step="1" class="input w-full" />
            </label>
            <label class="text-sm text-slate-300 md:col-span-2">
              <span class="mb-1 block text-xs text-slate-400">Approval max threshold</span>
              <input [(ngModel)]="riskConfigForm.threshold_approval_max" type="number" min="0" max="100" step="1" class="input w-full" />
            </label>
          </div>

          <div class="mt-4 flex items-center gap-3">
            <button
              (click)="saveRiskConfig()"
              [disabled]="riskConfigSaving() || riskConfigLoading()"
              class="btn-primary"
            >
              {{ riskConfigSaving() ? 'Saving…' : 'Save risk configuration' }}
            </button>
            <span class="text-xs text-slate-500">
              Resource sensitivity continues using the backend’s current default weight.
            </span>
          </div>
        }
      </div>

      <!-- Governance Settings -->
      <div class="card mb-6">
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 class="text-base font-semibold text-slate-100 mb-1">Governance Settings</h2>
            <p class="text-sm text-slate-400">
              Controls what happens when an agent request matches no active policy.
            </p>
          </div>
          <span class="rounded-full border border-slate-700 px-2 py-1 text-[11px] uppercase tracking-wide text-slate-400">
            Admin only
          </span>
        </div>

        @if (orgSettingsError()) {
          <div class="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {{ orgSettingsError() }}
          </div>
        }

        @if (orgSettingsSaved()) {
          <div class="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            Governance settings saved.
          </div>
        }

        @if (org()?.role !== 'admin') {
          <p class="mt-4 text-sm text-slate-500">Only admins can update governance settings.</p>
        } @else {
          <div class="mt-4 space-y-4">
            <div>
              <label class="block text-xs font-medium text-slate-300 mb-2">No-policy fallback action</label>
              <div class="space-y-2">
                <label class="flex items-start gap-3 cursor-pointer rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3 hover:border-slate-700 transition-colors"
                       [class.border-indigo-500]="noPolicyAction === 'deny'">
                  <input type="radio" [(ngModel)]="noPolicyAction" value="deny" class="mt-0.5 accent-indigo-500" />
                  <div>
                    <span class="text-sm font-medium text-slate-100">Deny</span>
                    <p class="text-xs text-slate-500 mt-0.5">All requests with no matching policy are blocked. Safest default — use when policies should be exhaustive.</p>
                  </div>
                </label>
                <label class="flex items-start gap-3 cursor-pointer rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3 hover:border-slate-700 transition-colors"
                       [class.border-indigo-500]="noPolicyAction === 'allow'">
                  <input type="radio" [(ngModel)]="noPolicyAction" value="allow" class="mt-0.5 accent-indigo-500" />
                  <div>
                    <span class="text-sm font-medium text-slate-100">Allow</span>
                    <p class="text-xs text-slate-500 mt-0.5">Requests with no matching policy pass through. Risk scoring and compliance checks still apply. Use when policies cover only sensitive actions.</p>
                  </div>
                </label>
                <label class="flex items-start gap-3 cursor-pointer rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3 hover:border-slate-700 transition-colors"
                       [class.border-indigo-500]="noPolicyAction === 'approval_required'">
                  <input type="radio" [(ngModel)]="noPolicyAction" value="approval_required" class="mt-0.5 accent-indigo-500" />
                  <div>
                    <span class="text-sm font-medium text-slate-100">Require approval</span>
                    <p class="text-xs text-slate-500 mt-0.5">Unmatched requests queue for human review. High-trust mode — approve selectively while building policy coverage.</p>
                  </div>
                </label>
              </div>
            </div>

            <div class="flex items-center gap-3">
              <button
                (click)="saveOrgSettings()"
                [disabled]="orgSettingsSaving()"
                class="btn-primary"
              >
                {{ orgSettingsSaving() ? 'Saving…' : 'Save governance settings' }}
              </button>
            </div>
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
  readonly availableApiKeyScopes = [...AVAILABLE_API_KEY_SCOPES];
  readonly orgApiKeys = signal<OrgApiKey[]>([]);
  readonly orgApiKeysLoading = signal(false);
  readonly orgApiKeysError = signal('');
  readonly creatingOrgApiKey = signal(false);
  readonly createdOrgApiKey = signal<OrgApiKeyCreateResponse | null>(null);
  readonly revokingOrgApiKeyIds = signal<Record<string, boolean>>({});
  readonly riskConfig = signal<OrgRiskConfig | null>(null);
  readonly riskConfigLoading = signal(false);
  readonly riskConfigSaving = signal(false);
  readonly riskConfigError = signal('');
  readonly riskConfigSaved = signal(false);
  readonly orgSettings = signal<OrgSettings | null>(null);
  readonly orgSettingsSaving = signal(false);
  readonly orgSettingsSaved = signal(false);
  readonly orgSettingsError = signal('');

  noPolicyAction: 'deny' | 'allow' | 'approval_required' = 'deny';

  ssoEnabled = false;
  ssoAutoJoin = false;
  ssoProviderInput = '';
  ssoMetadataUrlInput = '';
  ssoMetadataXmlInput = '';
  ssoEntityIdInput = '';
  ssoDomainsInput = '';
  ssoDefaultRole: 'admin' | 'operator' | 'viewer' = 'viewer';
  orgApiKeyNameInput = '';
  selectedOrgApiKeyScopes: AvailableApiKeyScope[] = [...AVAILABLE_API_KEY_SCOPES];
  riskConfigForm: RiskConfigFormModel = defaultRiskConfigForm();

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
    this.orgApiKeys.set([]);
    this.createdOrgApiKey.set(null);
    this.riskConfig.set(null);
    this.showKey.set(false);
  }

  toggleOrgApiKeyScope(scope: AvailableApiKeyScope, checked: boolean): void {
    if (checked) {
      this.selectedOrgApiKeyScopes = Array.from(new Set([...this.selectedOrgApiKeyScopes, scope]));
      return;
    }
    this.selectedOrgApiKeyScopes = this.selectedOrgApiKeyScopes.filter((item) => item !== scope);
  }

  resetOrgApiKeyScopes(): void {
    this.selectedOrgApiKeyScopes = [...AVAILABLE_API_KEY_SCOPES];
  }

  createOrgApiKey(): void {
    if (!this.orgApiKeyNameInput.trim()) {
      this.orgApiKeysError.set('Provide a name for the scoped API key.');
      return;
    }
    if (!this.selectedOrgApiKeyScopes.length) {
      this.orgApiKeysError.set('Select at least one scope before creating a key.');
      return;
    }

    this.creatingOrgApiKey.set(true);
    this.orgApiKeysError.set('');
    this.orgSvc
      .createApiKey({
        name: this.orgApiKeyNameInput.trim(),
        scopes: this.selectedOrgApiKeyScopes,
      })
      .subscribe({
        next: (created) => {
          this.creatingOrgApiKey.set(false);
          this.createdOrgApiKey.set(created);
          this.orgApiKeyNameInput = '';
          this.resetOrgApiKeyScopes();
          this.orgApiKeys.update((keys) => [created, ...keys]);
        },
        error: () => {
          this.creatingOrgApiKey.set(false);
          this.orgApiKeysError.set('Unable to create a scoped API key right now.');
        },
      });
  }

  revokeOrgApiKey(keyId: string): void {
    this.revokingOrgApiKeyIds.update((state) => ({ ...state, [keyId]: true }));
    this.orgApiKeysError.set('');
    this.orgSvc.revokeApiKey(keyId).subscribe({
      next: () => {
        this.revokingOrgApiKeyIds.update((state) => {
          const next = { ...state };
          delete next[keyId];
          return next;
        });
        this.orgApiKeys.update((keys) =>
          keys.map((key) => (key.id === keyId ? { ...key, revoked: true } : key))
        );
      },
      error: () => {
        this.revokingOrgApiKeyIds.update((state) => {
          const next = { ...state };
          delete next[keyId];
          return next;
        });
        this.orgApiKeysError.set('Unable to revoke this API key right now.');
      },
    });
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
    this.orgSvc.getMe().subscribe({
      next: (o) => {
        this.org.set(o);
        if (o.role === 'admin') {
          this.loadScopedApiKeys();
          this.loadRiskConfig();
          this.loadOrgSettings();
        } else {
          this.orgApiKeys.set([]);
          this.orgApiKeysError.set('');
          this.riskConfig.set(null);
          this.riskConfigError.set('');
        }
      },
    });
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

  private loadScopedApiKeys(): void {
    this.orgApiKeysLoading.set(true);
    this.orgApiKeysError.set('');
    this.orgSvc.listApiKeys().subscribe({
      next: (keys) => {
        this.orgApiKeys.set(keys);
        this.orgApiKeysLoading.set(false);
      },
      error: () => {
        this.orgApiKeysLoading.set(false);
        this.orgApiKeysError.set('Scoped API keys are not available right now.');
      },
    });
  }

  private loadRiskConfig(): void {
    this.riskConfigLoading.set(true);
    this.riskConfigError.set('');
    this.orgSvc.getRiskConfig().subscribe({
      next: (config) => {
        this.applyRiskConfig(config);
        this.riskConfigLoading.set(false);
      },
      error: () => {
        this.riskConfigLoading.set(false);
        this.riskConfigError.set('Unable to load the risk configuration.');
      },
    });
  }

  private loadOrgSettings(): void {
    this.orgSvc.getSettings().subscribe({
      next: (s) => {
        this.orgSettings.set(s);
        this.noPolicyAction = s.no_policy_action;
      },
      error: () => this.orgSettingsError.set('Unable to load governance settings.'),
    });
  }

  saveOrgSettings(): void {
    this.orgSettingsSaving.set(true);
    this.orgSettingsError.set('');
    this.orgSettingsSaved.set(false);
    this.orgSvc.updateSettings({ no_policy_action: this.noPolicyAction }).subscribe({
      next: (s) => {
        this.orgSettings.set(s);
        this.noPolicyAction = s.no_policy_action;
        this.orgSettingsSaving.set(false);
        this.orgSettingsSaved.set(true);
        setTimeout(() => this.orgSettingsSaved.set(false), 3000);
      },
      error: () => {
        this.orgSettingsSaving.set(false);
        this.orgSettingsError.set('Unable to save governance settings.');
      },
    });
  }

  saveRiskConfig(): void {
    this.riskConfigSaving.set(true);
    this.riskConfigError.set('');
    this.riskConfigSaved.set(false);
    this.orgSvc.updateRiskConfig({ ...this.riskConfigForm }).subscribe({
      next: (config) => {
        this.applyRiskConfig(config);
        this.riskConfigSaving.set(false);
        this.riskConfigSaved.set(true);
        setTimeout(() => this.riskConfigSaved.set(false), 3000);
      },
      error: () => {
        this.riskConfigSaving.set(false);
        this.riskConfigError.set('Unable to save the risk configuration.');
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

  private applyRiskConfig(config: OrgRiskConfig): void {
    this.riskConfig.set(config);
    this.riskConfigForm = {
      weight_action_severity: config.weight_action_severity,
      weight_context_signals: config.weight_context_signals,
      weight_rate_pattern: config.weight_rate_pattern,
      weight_agent_trust: config.weight_agent_trust,
      weight_amount_scale: config.weight_amount_scale,
      threshold_allow_max: config.threshold_allow_max,
      threshold_approval_max: config.threshold_approval_max,
    };
  }
}
