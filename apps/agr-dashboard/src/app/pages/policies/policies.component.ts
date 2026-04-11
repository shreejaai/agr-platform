import { Component, inject, OnInit, ChangeDetectionStrategy, signal, HostListener } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import {
  PolicyAnalyticsSummary,
  PolicyService,
  SimulateRequest,
  SimulateResponse,
} from '../../services/policy.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { ComplianceFindingsComponent } from '../../shared/components/compliance-findings/compliance-findings.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { RiskBreakdownComponent } from '../../shared/components/risk-breakdown/risk-breakdown.component';
import {
  Policy,
  PolicyCreate,
  PolicyImportResponse,
  PolicyImportResult,
  PolicyTemplate,
  PolicyTestCaseResult,
  PolicyTestSuite,
  PolicyTestSuiteRunResult,
} from '../../core/models/policy.model';

/** Friendly form fields — converted to PolicyCreate (cedar_rule) on submit. */
interface PolicyForm {
  name: string;
  effect: 'allow' | 'deny' | 'require_approval';
  action: string;
  resource_attr: string;
  resource_value: string;
  /** Optional: context attribute condition (e.g. "environment") */
  context_attr: string;
  /** Operator for context condition: == | != | > | < | >= | <= */
  context_op: '==' | '!=' | '>' | '<' | '>=' | '<=';
  context_value: string;
  /** Optional: numeric threshold (e.g. amount > 10000) */
  threshold_attr: string;
  threshold_op: '>' | '<' | '>=' | '<=';
  threshold_value: string;
  level: 'org' | 'project' | 'agent';
  /** When true, shows raw Cedar editor instead of friendly form */
  advancedMode: boolean;
}

interface PolicyEditForm {
  name: string;
  cedar_rule: string;
}

interface PolicyAnalytics {
  totalEvaluations: number;
  lastTriggeredAt: string | null;
  decisions: {
    ALLOW: number;
    DENY: number;
    APPROVAL_REQUIRED: number;
  };
}

/** Generate a Cedar rule string from friendly form fields (deterministic, no AI). */
function buildCedarRule(form: PolicyForm): string {
  const action = form.action.trim();
  const hasResource = form.resource_attr.trim() && form.resource_value.trim();
  const hasContext = form.context_attr.trim() && form.context_value.trim();
  const hasThreshold = form.threshold_attr.trim() && form.threshold_value.trim();

  // Build when-clause conditions
  const conditions: string[] = [];
  if (hasResource) {
    const attr = form.resource_attr.trim();
    const val = form.resource_value.trim();
    conditions.push(`resource has ${attr} && resource.${attr} == "${val}"`);
  }
  if (hasContext) {
    const attr = form.context_attr.trim();
    const val = form.context_value.trim();
    const op = form.context_op || '==';
    // Numeric ops don't need quotes; string equality does
    const numericOps = new Set(['>', '<', '>=', '<=']);
    const valExpr = numericOps.has(op) ? val : `"${val}"`;
    conditions.push(`context has ${attr} && context.${attr} ${op} ${valExpr}`);
  }
  if (hasThreshold) {
    const attr = form.threshold_attr.trim();
    const val = form.threshold_value.trim();
    const op = form.threshold_op || '>';
    conditions.push(`context has ${attr} && context.${attr} ${op} ${val}`);
  }

  const whenClause = conditions.length > 0
    ? `\nwhen { ${conditions.join(' &&\n       ')} }`
    : '';

  if (form.effect === 'require_approval') {
    return (
      `forbid(principal, action == Action::"${action}", resource)` +
      whenClause +
      '\nunless { context has approval_status && context.approval_status == "approved" };'
    );
  }

  const kw = form.effect === 'allow' ? 'permit' : 'forbid';
  return `${kw}(principal, action == Action::"${action}", resource)${whenClause};`;
}

/** Quick-fill templates for the policy builder. */
const BUILDER_TEMPLATES: Array<{ label: string; form: Partial<PolicyForm> }> = [
  {
    label: 'Allow web search',
    form: { effect: 'allow', action: 'web_search', resource_attr: '', resource_value: '' },
  },
  {
    label: 'Deny file delete',
    form: { effect: 'deny', action: 'file_delete', resource_attr: '', resource_value: '' },
  },
  {
    label: 'Require approval — production deploy',
    form: {
      effect: 'require_approval',
      action: 'deploy',
      context_attr: 'environment',
      context_op: '==',
      context_value: 'production',
    },
  },
  {
    label: 'Require approval — large transfer',
    form: {
      effect: 'require_approval',
      action: 'transfer_funds',
      threshold_attr: 'amount',
      threshold_op: '>',
      threshold_value: '10000',
    },
  },
  {
    label: 'Deny customer data export',
    form: { effect: 'deny', action: 'export_customer_data', resource_attr: '', resource_value: '' },
  },
  {
    label: 'Allow read-only DB query',
    form: { effect: 'allow', action: 'db_query', resource_attr: '', resource_value: '' },
  },
];

/** Derive human-readable effect from a cedar_rule string. */
function deriveEffect(cedar_rule: string): string {
  const r = cedar_rule.trim();
  if (r.includes('unless') && r.includes('approval_status')) return 'approval';
  return r.startsWith('permit') ? 'allow' : 'deny';
}

/** Extract first Action::"name" from a cedar_rule string. */
function deriveAction(cedar_rule: string): string {
  const m = /Action::"([^"]+)"/.exec(cedar_rule);
  return m?.[1] ?? '—';
}

const SAMPLE_POLICIES_JSON = JSON.stringify(
  {
    policies: [
      {
        name: 'allow-web-search',
        level: 'org',
        cedar_rule: 'permit(principal, action == Action::"web_search", resource);',
        active: true,
      },
      {
        name: 'deny-file-delete',
        level: 'org',
        cedar_rule: 'forbid(principal, action == Action::"file_delete", resource);',
        active: true,
      },
      {
        name: 'require-approval-production-deploy',
        level: 'org',
        cedar_rule:
          'forbid(principal, action == Action::"deploy", resource)\nwhen { resource has environment && resource.environment == "production" }\nunless { context has approval_status && context.approval_status == "approved" };',
        active: true,
      },
      {
        name: 'allow-read-only-db',
        level: 'project',
        cedar_rule: 'permit(principal, action == Action::"db_query", resource);',
        active: true,
      },
      {
        name: 'deny-external-api-calls',
        level: 'agent',
        cedar_rule: 'forbid(principal, action == Action::"http_request", resource)\nwhen { resource has domain && resource.domain == "external" };',
        active: false,
      },
    ],
    dry_run: false,
    overwrite: false,
  },
  null,
  2,
);

@Component({
  selector: 'agr-policies',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    DecimalPipe,
    BadgeComponent,
    RiskBreakdownComponent,
    ComplianceFindingsComponent,
    RelativeTimePipe,
    RouterLink,
  ],
  template: `
    <div class="space-y-4">
      <!-- Toolbar -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-slate-100">Policies</h1>
          <p class="text-sm text-slate-400 mt-1">Cedar-based governance rules evaluated on every tool call.</p>
        </div>
        <div class="flex items-center gap-2">
          <button (click)="exportAll()" class="btn-secondary text-sm">Export JSON</button>
          <button (click)="openImport()" class="btn-secondary text-sm">Import</button>
          <button (click)="openCreate()" class="btn-primary text-sm">+ New policy</button>
        </div>
      </div>

      @if (templateActionMessage()) {
        <div class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
          {{ templateActionMessage() }}
        </div>
      }

      @if (templateError()) {
        <div class="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {{ templateError() }}
        </div>
      }

      <div class="card border border-slate-800">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold text-slate-100">Template Library</h2>
            <p class="text-sm text-slate-400 mt-1">Production-oriented starter packs for API governance, data access, and approval gates.</p>
          </div>
          <button (click)="loadTemplates()" class="btn-secondary text-sm" [disabled]="templatesLoading()">
            {{ templatesLoading() ? 'Refreshing…' : 'Refresh templates' }}
          </button>
        </div>

        @if (templatesLoading() && !templates().length) {
          <p class="mt-4 text-sm text-slate-400">Loading template library…</p>
        } @else {
          <div class="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
            @for (template of templates(); track template.id) {
              <article class="rounded-xl border border-slate-800 bg-slate-950/40 p-4 flex flex-col gap-4">
                <div class="space-y-2">
                  <div class="flex items-center justify-between gap-3">
                    <h3 class="text-sm font-semibold text-slate-100">{{ template.name }}</h3>
                    <span class="text-[11px] uppercase tracking-wider text-slate-500">{{ template.category }}</span>
                  </div>
                  <p class="text-sm text-slate-400 leading-6">{{ template.description }}</p>
                  <div class="flex flex-wrap gap-2">
                    @for (tag of template.tags; track tag) {
                      <span class="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400">{{ tag }}</span>
                    }
                  </div>
                </div>
                <div class="mt-auto flex items-center justify-between gap-3">
                  <span class="text-xs text-slate-500">{{ template.policies.length }} policies</span>
                  <button class="btn-primary text-sm" (click)="importTemplate(template)">
                    Import template
                  </button>
                </div>
              </article>
            }
          </div>
        }
      </div>

      <!-- Import Modal (full-screen overlay) -->
      @if (showImport()) {
        <div
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          tabindex="-1"
          (click)="onOverlayClick($event)"
          (keydown.escape)="closeImport()"
        >
          <div
            class="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto"
            role="dialog"
            aria-modal="true"
            aria-label="Import Policies"
            tabindex="-1"
            (click)="$event.stopPropagation()"
            (keydown)="$event.stopPropagation()"
          >
            <!-- Modal header -->
            <div class="flex items-center justify-between px-6 py-4 border-b border-slate-700">
              <div>
                <h2 class="text-base font-semibold text-slate-100">Import Policies</h2>
                <p class="text-xs text-slate-400 mt-0.5">Upload a .json or .yaml file, or paste content directly.</p>
              </div>
              <button
                (click)="closeImport()"
                class="text-slate-500 hover:text-slate-200 transition-colors text-lg leading-none p-1 rounded hover:bg-slate-800"
                aria-label="Close"
              >✕</button>
            </div>

            <!-- Modal body -->
            <div class="px-6 py-4 space-y-4">

              <!-- File drop zone -->
              <div
                class="border-2 border-dashed border-slate-600 rounded-lg p-8 text-center cursor-pointer hover:border-indigo-500 hover:bg-indigo-500/5 transition-colors"
                role="button"
                tabindex="0"
                aria-label="Upload policy file"
                (click)="fileInput.click()"
                (keydown.enter)="fileInput.click()"
                (keydown.space)="fileInput.click()"
                (dragover)="$event.preventDefault()"
                (drop)="onDrop($event)"
              >
                <input
                  #fileInput
                  type="file"
                  class="hidden"
                  accept=".json,.yaml,.yml,.cedar,.txt"
                  (change)="onFileSelected($event)"
                />
                @if (selectedFileName()) {
                  <p class="text-sm text-indigo-400 font-medium">📄 {{ selectedFileName() }}</p>
                  <p class="text-xs text-slate-500 mt-1">Click to change file</p>
                } @else {
                  <div class="flex justify-center mb-3">
                    <svg class="w-8 h-8 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                            d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                    </svg>
                  </div>
                  <p class="text-slate-400 text-sm">Drop .json or .yaml file here</p>
                  <p class="text-slate-500 text-xs mt-1">or click to browse</p>
                }
              </div>

              <!-- Sample download link -->
              <div class="flex justify-end">
                <button
                  (click)="downloadSample()"
                  class="text-xs text-sky-400 hover:text-sky-300 underline transition-colors"
                >
                  Download sample JSON
                </button>
              </div>

              <!-- Paste area -->
              <div>
                <label for="import-textarea" class="block text-xs text-slate-400 mb-1">Or paste JSON / YAML content</label>
                <textarea
                  id="import-textarea"
                  [(ngModel)]="importText"
                  class="input w-full font-mono text-xs"
                  rows="6"
                  placeholder='{"policies": [{"name": "allow-web-search", "level": "org", "cedar_rule": "permit(...);"}]}'
                ></textarea>
              </div>

              <!-- Options -->
              <div class="flex items-center gap-6 text-sm">
                <label class="flex items-center gap-2 cursor-pointer select-none">
                  <input type="checkbox" [(ngModel)]="importDryRun" class="rounded" />
                  <span class="text-slate-300">Dry run <span class="text-slate-500 text-xs">(preview without saving)</span></span>
                </label>
                <label class="flex items-center gap-2 cursor-pointer select-none">
                  <input type="checkbox" [(ngModel)]="importOverwrite" class="rounded" />
                  <span class="text-slate-300">Overwrite duplicates</span>
                </label>
              </div>

              <!-- Error -->
              @if (importError()) {
                <div class="rounded-lg bg-red-500/10 border border-red-500/30 px-4 py-3 text-sm text-red-400">
                  {{ importError() }}
                </div>
              }

              <!-- Results -->
              @if (importResult()) {
                <div class="rounded-lg border border-slate-700 overflow-hidden">
                  <!-- Summary bar -->
                  <div class="px-4 py-2.5 bg-slate-800/50 flex items-center gap-4 text-xs flex-wrap">
                    <span class="text-slate-300">Total: <strong>{{ importResult()!.total }}</strong></span>
                    <span class="text-emerald-400">+ {{ importResult()!.created }} created</span>
                    <span class="text-amber-400">↻ {{ importResult()!.updated }} updated</span>
                    <span class="text-slate-500">○ {{ importResult()!.skipped }} skipped</span>
                    @if (importResult()!.errors > 0) {
                      <span class="text-red-400">✕ {{ importResult()!.errors }} errors</span>
                    }
                    @if (importResult()!.dry_run) {
                      <span class="ml-auto text-sky-400 font-medium">DRY RUN — nothing saved</span>
                    }
                  </div>
                  <!-- Per-row table -->
                  <table class="w-full text-xs">
                    @for (r of importResult()!.results; track r.name) {
                      <tr class="border-t border-slate-700/50 hover:bg-slate-800/30">
                        <td class="px-4 py-2 text-slate-300 font-medium">{{ r.name }}</td>
                        <td class="px-4 py-2 w-24">
                          <span [class]="statusBadgeClass(r.status)">{{ r.status }}</span>
                        </td>
                        <td class="px-4 py-2 text-slate-500 text-xs">{{ r.error ?? '' }}</td>
                      </tr>
                    }
                  </table>
                </div>
              }

            </div>

            <!-- Modal footer -->
            <div class="flex items-center justify-between px-6 py-4 border-t border-slate-700 bg-slate-900/50">
              <button
                (click)="closeImport()"
                class="text-sm text-slate-400 hover:text-slate-200 transition-colors"
              >Cancel</button>
              <div class="flex gap-2">
                @if (importResult() && importResult()!.dry_run && importResult()!.errors === 0) {
                  <button
                    (click)="confirmImport()"
                    [disabled]="importing()"
                    class="btn-primary text-sm"
                  >
                    {{ importing() ? 'Importing…' : 'Confirm Import (' + importResult()!.total + ' policies)' }}
                  </button>
                } @else {
                  <button
                    (click)="runImport()"
                    [disabled]="importing()"
                    class="btn-primary text-sm"
                  >
                    {{ importing() ? 'Processing…' : (importDryRun ? 'Preview' : 'Import') }}
                  </button>
                }
              </div>
            </div>

          </div>
        </div>
      }

      <!-- Create form -->
      @if (showForm() && !editingPolicy()) {
        <div class="card border border-indigo-500/30">
          <h2 class="text-base font-semibold text-slate-100 mb-4">New Policy</h2>
          <div class="space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="policy-name" class="block text-xs text-slate-400 mb-1">Policy name</label>
                <input id="policy-name" [(ngModel)]="form.name" class="input w-full" placeholder="allow-web-search" />
              </div>
              <div>
                <label for="policy-level" class="block text-xs text-slate-400 mb-1">Applies to</label>
                <select id="policy-level" [(ngModel)]="form.level" class="input w-full">
                  <option value="org">Entire org</option>
                  <option value="project">Project</option>
                  <option value="agent">Specific agent</option>
                </select>
              </div>
            </div>

            <!-- Quick templates -->
            <div>
              <p class="text-xs text-slate-400 mb-2">Quick templates</p>
              <div class="flex flex-wrap gap-2">
                @for (tpl of builderTemplates; track tpl.label) {
                  <button
                    type="button"
                    (click)="applyBuilderTemplate(tpl.form)"
                    class="px-2.5 py-1 text-xs rounded-full border border-slate-700
                           text-slate-400 hover:border-indigo-500 hover:text-indigo-300 transition-colors"
                  >{{ tpl.label }}</button>
                }
              </div>
            </div>

            <!-- Mode toggle: builder vs raw Cedar -->
            <div class="flex items-center gap-3">
              <label class="flex items-center gap-2 cursor-pointer text-xs text-slate-400 select-none">
                <input type="checkbox" [(ngModel)]="form.advancedMode" class="rounded" />
                Raw Cedar editor
              </label>
              @if (form.advancedMode) {
                <span class="text-xs text-amber-400">Advanced mode — edit Cedar rule directly</span>
              }
            </div>

            @if (!form.advancedMode) {
              <!-- Friendly builder -->
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label for="policy-effect" class="block text-xs text-slate-400 mb-1">Effect</label>
                  <select id="policy-effect" [(ngModel)]="form.effect" class="input w-full">
                    <option value="allow">Allow</option>
                    <option value="deny">Deny</option>
                    <option value="require_approval">Require approval (approval gate)</option>
                  </select>
                </div>
                <div>
                  <label for="policy-action" class="block text-xs text-slate-400 mb-1">Action (tool name)</label>
                  <input id="policy-action" [(ngModel)]="form.action" class="input w-full" placeholder="web_search" />
                </div>
              </div>

              <!-- Resource condition (optional) -->
              <div>
                <p class="text-xs text-slate-400 mb-1">Resource condition <span class="text-slate-600">(optional)</span></p>
                <div class="grid grid-cols-2 gap-3">
                  <input [(ngModel)]="form.resource_attr" class="input w-full text-sm" placeholder="Attribute: environment" />
                  <input [(ngModel)]="form.resource_value" class="input w-full text-sm" placeholder="Value: production" />
                </div>
              </div>

              <!-- Context condition (optional) -->
              <div>
                <p class="text-xs text-slate-400 mb-1">Context condition <span class="text-slate-600">(optional)</span></p>
                <div class="grid grid-cols-3 gap-2">
                  <input [(ngModel)]="form.context_attr" class="input text-sm" placeholder="Attribute: environment" />
                  <select [(ngModel)]="form.context_op" class="input text-sm">
                    <option value="==">== (equals)</option>
                    <option value="!=">!= (not equals)</option>
                    <option value=">">> (greater than)</option>
                    <option value="<">&#60; (less than)</option>
                    <option value=">=">>= (greater or equal)</option>
                    <option value="<=">&#60;= (less or equal)</option>
                  </select>
                  <input [(ngModel)]="form.context_value" class="input text-sm" placeholder="Value: production" />
                </div>
              </div>

              <!-- Numeric threshold (optional) -->
              <div>
                <p class="text-xs text-slate-400 mb-1">Numeric threshold <span class="text-slate-600">(optional — e.g. amount &gt; 10000)</span></p>
                <div class="grid grid-cols-3 gap-2">
                  <input [(ngModel)]="form.threshold_attr" class="input text-sm" placeholder="Attribute: amount" />
                  <select [(ngModel)]="form.threshold_op" class="input text-sm">
                    <option value=">">> (greater than)</option>
                    <option value="<">&#60; (less than)</option>
                    <option value=">=">>= (greater or equal)</option>
                    <option value="<=">&#60;= (less or equal)</option>
                  </select>
                  <input [(ngModel)]="form.threshold_value" class="input text-sm" placeholder="10000" />
                </div>
              </div>

              <!-- Live preview -->
              <div>
                <p class="text-xs text-slate-400 mb-1">Generated Cedar rule (live preview)</p>
                <pre class="text-xs bg-slate-900 rounded p-3 text-indigo-300 overflow-x-auto min-h-[2.5rem]">{{ previewCedarRule }}</pre>
              </div>
            } @else {
              <!-- Raw Cedar editor -->
              <div>
                <label for="policy-cedar-raw" class="block text-xs text-slate-400 mb-1">Cedar rule</label>
                <textarea
                  id="policy-cedar-raw"
                  [(ngModel)]="rawCedarRule"
                  class="input w-full font-mono text-xs"
                  rows="6"
                  placeholder='permit(principal, action == Action::"web_search", resource);'
                ></textarea>
                <p class="text-xs text-slate-500 mt-1">Write Cedar directly. Must start with permit or forbid and end with ;</p>
              </div>
            }

            @if (formError()) {
              <p class="text-sm text-red-400">{{ formError() }}</p>
            }

            <div class="flex gap-2">
              <button (click)="create()" [disabled]="saving()" class="btn-primary text-sm">
                {{ saving() ? 'Saving…' : 'Create policy' }}
              </button>
              <button (click)="cancelForm()"
                      class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors">
                Cancel
              </button>
            </div>
          </div>
        </div>
      }

      <!-- Edit form -->
      @if (editingPolicy()) {
        <div class="card border border-amber-500/30">
          <h2 class="text-base font-semibold text-slate-100 mb-4">Edit Policy</h2>
          <div class="space-y-3">
            <div>
              <label for="edit-policy-name" class="block text-xs text-slate-400 mb-1">Policy name</label>
              <input id="edit-policy-name" [(ngModel)]="editForm.name" class="input w-full" />
            </div>
            <div>
              <label for="edit-policy-rule" class="block text-xs text-slate-400 mb-1">Cedar rule</label>
              <textarea id="edit-policy-rule" [(ngModel)]="editForm.cedar_rule"
                        class="input w-full font-mono text-xs"
                        rows="5"></textarea>
            </div>

            @if (formError()) {
              <p class="text-sm text-red-400">{{ formError() }}</p>
            }

            <div class="flex gap-2">
              <button (click)="saveEdit()" [disabled]="saving()" class="btn-primary text-sm">
                {{ saving() ? 'Saving…' : 'Save changes' }}
              </button>
              <button (click)="cancelForm()"
                      class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors">
                Cancel
              </button>
            </div>
          </div>
        </div>
      }

      <!-- Search / filter bar -->
      <div class="card">
        <div class="flex flex-wrap gap-3 items-end">
          <div class="flex-1 min-w-[180px]">
            <label for="policy-search-query" class="block text-xs text-slate-400 mb-1">Search by name</label>
            <input
              id="policy-search-query"
              [(ngModel)]="searchQuery"
              (keydown.enter)="loadList()"
              (blur)="loadList()"
              class="input w-full text-sm"
              placeholder="allow-web-search…"
            />
          </div>
          <div class="w-36">
            <label for="policy-filter-state" class="block text-xs text-slate-400 mb-1">State</label>
            <select id="policy-filter-state" [(ngModel)]="filterState" (ngModelChange)="loadList()" class="input w-full text-sm">
              <option value="">Active (default)</option>
              <option value="active">Active</option>
              <option value="draft">Draft</option>
              <option value="archived">Archived</option>
            </select>
          </div>
          <div class="w-44">
            <label for="policy-filter-effect" class="block text-xs text-slate-400 mb-1">Effect</label>
            <select id="policy-filter-effect" [(ngModel)]="filterEffect" (ngModelChange)="loadList()" class="input w-full text-sm">
              <option value="">All effects</option>
              <option value="allow">Allow</option>
              <option value="deny">Deny</option>
              <option value="approval_required">Require approval</option>
            </select>
          </div>
          <button
            (click)="searchQuery = ''; filterState = ''; filterEffect = ''; loadList()"
            class="text-xs text-slate-500 hover:text-slate-200 underline self-end pb-1"
          >Clear</button>
        </div>
      </div>

      <!-- List -->
      @if (loading()) {
        <div class="py-16 text-center text-slate-500 text-sm">Loading…</div>
      } @else if (items().length === 0) {
        <div class="card py-16 text-center">
          <p class="text-slate-400">No policies match your filters.</p>
          <p class="text-slate-500 text-xs mt-1">Create your first policy to start governing agent tool calls.</p>
        </div>
      } @else {
        <div class="card overflow-hidden p-0">
          <table class="w-full text-sm">
            <thead>
              <tr>
                <th class="table-header">Name</th>
                <th class="table-header">Effect</th>
                <th class="table-header">Action</th>
                <th class="table-header">Level</th>
                <th class="table-header">Status</th>
                <th class="table-header"></th>
              </tr>
            </thead>
            <tbody>
	              @for (p of items(); track p.id) {
	                <tr class="table-row">
	                  <td class="table-cell font-medium text-slate-200">
	                    <div>{{ p.name }}</div>
	                    <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
	                      @if (policyAnalyticsLoading()[p.id]) {
	                        <span class="text-slate-500">Loading stats…</span>
	                      } @else if (policyAnalytics()[p.id]) {
	                        <span class="rounded-full border border-slate-700 px-2 py-0.5 text-slate-300">
	                          Total {{ policyAnalytics()[p.id]!.totalEvaluations }}
	                        </span>
	                        <span class="rounded-full border border-slate-700 px-2 py-0.5 text-slate-300">
	                          Last triggered {{ policyAnalytics()[p.id]!.lastTriggeredAt | relativeTime }}
	                        </span>
	                        <span class="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-emerald-300">
	                          ALLOW {{ policyAnalytics()[p.id]!.decisions.ALLOW }}
	                        </span>
	                        <span class="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-red-300">
	                          DENY {{ policyAnalytics()[p.id]!.decisions.DENY }}
	                        </span>
	                        <span class="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-amber-300">
	                          APPROVAL {{ policyAnalytics()[p.id]!.decisions.APPROVAL_REQUIRED }}
	                        </span>
	                      } @else {
	                        <a
	                          [routerLink]="['/audit']"
	                          [queryParams]="{ policy_id: p.id }"
	                          class="text-sky-400 transition-colors hover:text-sky-300"
	                        >
	                          View in Audit Log
	                        </a>
	                      }
	                    </div>
	                  </td>
	                  <td class="table-cell">
	                    <agr-badge [variant]="effectVariant(p.cedar_rule)">
	                      {{ deriveEffect(p.cedar_rule) }}
                    </agr-badge>
                  </td>
                  <td class="table-cell font-mono text-xs text-slate-300">
                    {{ deriveAction(p.cedar_rule) }}
                  </td>
                  <td class="table-cell text-xs text-slate-400">{{ p.level }}</td>
                  <td class="table-cell">
                    <agr-badge [variant]="p.active ? 'success' : 'neutral'">
                      {{ p.active ? 'enabled' : 'disabled' }}
                    </agr-badge>
                  </td>
                  <td class="table-cell text-right">
                    <button
                      (click)="openEdit(p)"
                      class="text-xs text-slate-500 hover:text-slate-200 mr-3 transition-colors"
                    >Edit</button>
                    <button
                      (click)="toggle(p)"
                      class="text-xs text-slate-500 hover:text-slate-200 mr-3 transition-colors"
                    >{{ p.active ? 'Disable' : 'Enable' }}</button>
                    <button
                      (click)="remove(p.id)"
                      class="text-xs text-red-500/70 hover:text-red-400 transition-colors"
                    >Delete</button>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }

      <!-- Policy Simulation Panel -->
	      <div class="card border border-slate-700">
	        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-base font-semibold text-slate-100">Policy Simulation</h2>
            <p class="text-xs text-slate-400 mt-0.5">Test how your policies evaluate a hypothetical tool call without executing it.</p>
          </div>
          <button
            (click)="toggleSimPanel()"
            class="text-xs text-slate-500 hover:text-slate-200 transition-colors"
          >{{ showSimPanel() ? 'Collapse ▲' : 'Expand ▼' }}</button>
        </div>

        @if (showSimPanel()) {
          <div class="space-y-3">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label for="sim-agent-id" class="block text-xs text-slate-400 mb-1">Agent ID</label>
                <input
                  id="sim-agent-id"
                  [(ngModel)]="simForm.agent_id"
                  class="input w-full text-sm font-mono"
                  placeholder="agent-abc123"
                />
              </div>
              <div>
                <label for="sim-action" class="block text-xs text-slate-400 mb-1">Action (tool name)</label>
                <input
                  id="sim-action"
                  [(ngModel)]="simForm.action"
                  class="input w-full text-sm font-mono"
                  placeholder="web_search"
                />
              </div>
            </div>
            <div>
              <label for="sim-resource" class="block text-xs text-slate-400 mb-1">Resource</label>
              <input
                id="sim-resource"
                [(ngModel)]="simForm.resource"
                class="input w-full text-sm font-mono"
                placeholder="https://example.com"
              />
            </div>
            <div>
              <label for="sim-context" class="block text-xs text-slate-400 mb-1">Context (JSON, optional)</label>
              <textarea
                id="sim-context"
                [(ngModel)]="simContextRaw"
                class="input w-full font-mono text-xs"
                rows="3"
                placeholder='{"environment": "production"}'
              ></textarea>
            </div>

            @if (simError()) {
              <p class="text-sm text-red-400">{{ simError() }}</p>
            }

            <button
              (click)="runSimulation()"
              [disabled]="simulating()"
              class="btn-primary text-sm"
            >
              {{ simulating() ? 'Simulating…' : 'Run Simulation' }}
            </button>

            <!-- Simulation Result -->
            @if (simResult()) {
              <div class="mt-4 rounded-xl border border-slate-700 overflow-hidden">
                <!-- Decision header -->
                <div [class]="simDecisionBg(simResult()!.decision) + ' px-5 py-4 flex items-center gap-3'">
                  <span [class]="simDecisionBadgeClass(simResult()!.decision)" class="text-sm font-bold tracking-wide px-3 py-1 rounded-full border">
                    {{ simResult()!.decision }}
                  </span>
                  <span class="text-sm text-slate-300">{{ simResult()!.reason }}</span>
                </div>

                <!-- Risk + trace details -->
                <div class="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 gap-4 bg-slate-900/40">
                  <!-- Risk -->
                  <div>
                    <p class="text-xs text-slate-500 uppercase tracking-wider mb-2">Risk</p>
                    <agr-risk-breakdown
                      [data]="{
                        score: simResult()!.risk_score,
                        level: simResult()!.risk_level,
                        factors: simResult()!.risk_factors
                      }"
                    />
                  </div>

                  <!-- Decision trace -->
                  <div>
                    <p class="text-xs text-slate-500 uppercase tracking-wider mb-2">Decision Trace</p>
                    <dl class="space-y-1 text-xs">
                      <div class="flex gap-2">
                        <dt class="text-slate-500 w-28 shrink-0">Policy source</dt>
                        <dd class="text-slate-300 font-mono truncate">{{ simResult()!.decision_trace.policy_source ?? '—' }}</dd>
                      </div>
                      <div class="flex gap-2">
                        <dt class="text-slate-500 w-28 shrink-0">Cedar decision</dt>
                        <dd class="text-slate-300 font-mono">{{ simResult()!.decision_trace.cedar_decision ?? '—' }}</dd>
                      </div>
                      <div class="flex gap-2">
                        <dt class="text-slate-500 w-28 shrink-0">Risk override</dt>
                        <dd [class]="simResult()!.decision_trace.risk_override ? 'text-amber-400' : 'text-slate-400'">
                          {{ simResult()!.decision_trace.risk_override ? 'Yes' : 'No' }}
                        </dd>
                      </div>
                    </dl>
                  </div>
                </div>

                <div class="px-5 py-4 border-t border-slate-800 bg-slate-950/40">
                  <agr-compliance-findings [findings]="simResult()!.compliance_findings" />
                </div>
              </div>
            }
          </div>
	        }
	      </div>

	      <div class="card border border-slate-700">
	        <div class="flex items-center justify-between gap-3 mb-4">
	          <div>
	            <h2 class="text-base font-semibold text-slate-100">Policy Test Suites</h2>
	            <p class="text-xs text-slate-400 mt-0.5">
	              Run saved backend test suites to verify expected decisions against the live policy engine.
	            </p>
	          </div>
	          @if (testSuitesLoading()) {
	            <span class="text-xs text-slate-500">Loading suites…</span>
	          }
	        </div>

	        @if (testSuiteError()) {
	          <div class="mb-4 rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
	            {{ testSuiteError() }}
	          </div>
	        }

	        @if (!testSuites().length && !testSuitesLoading()) {
	          <div class="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-5">
	            <p class="text-sm text-slate-300">No saved policy test suites yet.</p>
	            <p class="mt-2 text-xs text-slate-500">
	              You can still validate policy behavior with the simulation panel above or the backend test-suite APIs.
	            </p>
	          </div>
	        } @else {
	          <div class="space-y-4">
	            @for (suite of testSuites(); track suite.id) {
	              <article class="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
	                <div class="flex items-start justify-between gap-4 flex-wrap">
	                  <div>
	                    <h3 class="text-sm font-semibold text-slate-100">{{ suite.name }}</h3>
	                    @if (suite.description) {
	                      <p class="mt-1 text-sm text-slate-400">{{ suite.description }}</p>
	                    }
	                  </div>
	                  <button
	                    class="btn-primary text-sm"
	                    [disabled]="testSuiteRunning()[suite.id]"
	                    (click)="runTestSuite(suite.id)"
	                  >
	                    {{ testSuiteRunning()[suite.id] ? 'Running…' : 'Run All Tests' }}
	                  </button>
	                </div>

	                @if (testSuiteRuns()[suite.id]) {
	                  <div class="mt-3 flex flex-wrap gap-2 text-[11px]">
	                    <span class="rounded-full border border-slate-700 px-2 py-0.5 text-slate-300">
	                      {{ testSuiteRuns()[suite.id]!.total }} total
	                    </span>
	                    <span class="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-emerald-300">
	                      {{ testSuiteRuns()[suite.id]!.passed }} passed
	                    </span>
	                    <span class="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-red-300">
	                      {{ testSuiteRuns()[suite.id]!.failed }} failed
	                    </span>
	                    <span class="rounded-full border border-slate-700 px-2 py-0.5 text-slate-300">
	                      {{ testSuiteRuns()[suite.id]!.duration_ms | number:'1.0-0' }} ms
	                    </span>
	                  </div>
	                }

	                <div class="mt-4 overflow-x-auto">
	                  <table class="w-full text-xs">
	                    <thead>
	                      <tr class="border-b border-slate-800 text-left text-slate-500">
	                        <th class="pb-2 pr-4 font-medium">Agent</th>
	                        <th class="pb-2 pr-4 font-medium">Action</th>
	                        <th class="pb-2 pr-4 font-medium">Resource</th>
	                        <th class="pb-2 pr-4 font-medium">Expected</th>
	                        <th class="pb-2 font-medium">Last result</th>
	                      </tr>
	                    </thead>
	                    <tbody>
	                      @for (testCase of suite.test_cases; track testCase.name) {
	                        <tr class="border-b border-slate-900/80 text-slate-300 last:border-b-0">
	                          <td class="py-2 pr-4 font-mono">{{ testCase.agent_id }}</td>
	                          <td class="py-2 pr-4 font-mono">{{ testCase.action }}</td>
	                          <td class="py-2 pr-4 font-mono">{{ testCase.resource }}</td>
	                          <td class="py-2 pr-4">
	                            <span class="rounded-full border border-slate-700 px-2 py-0.5 text-slate-300">
	                              {{ testCase.expected_decision }}
	                            </span>
	                          </td>
	                          <td class="py-2">
	                            @if (lastTestCaseResult(suite.id, testCase.name)) {
	                              <span
	                                class="rounded-full px-2 py-0.5"
	                                [class]="
	                                  lastTestCaseResult(suite.id, testCase.name)!.passed
	                                    ? 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
	                                    : 'border border-red-500/30 bg-red-500/10 text-red-300'
	                                "
	                              >
	                                {{ lastTestCaseResult(suite.id, testCase.name)!.passed ? 'Pass' : 'Fail' }}
	                              </span>
	                            } @else {
	                              <span class="text-slate-500">Not run yet</span>
	                            }
	                          </td>
	                        </tr>
	                      }
	                    </tbody>
	                  </table>
	                </div>
	              </article>
	            }
	          </div>
	        }
	      </div>
	    </div>
	  `,
})
export class PoliciesComponent implements OnInit {
  private svc = inject(PolicyService);
  private route = inject(ActivatedRoute);

  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly showForm = signal(false);
  readonly formError = signal('');
  readonly items = signal<Policy[]>([]);

  // Search/filter state
  searchQuery = '';
  filterState: '' | 'draft' | 'active' | 'archived' = '';
  filterEffect: '' | 'allow' | 'deny' | 'approval_required' = '';
  readonly templates = signal<PolicyTemplate[]>([]);
  readonly templatesLoading = signal(false);
  readonly templateError = signal('');
  readonly templateActionMessage = signal('');
  readonly editingPolicy = signal<Policy | null>(null);
  readonly policyAnalytics = signal<Record<string, PolicyAnalytics | null>>({});
  readonly policyAnalyticsLoading = signal<Record<string, boolean>>({});
  readonly testSuites = signal<PolicyTestSuite[]>([]);
  readonly testSuitesLoading = signal(false);
  readonly testSuiteError = signal('');
  readonly testSuiteRuns = signal<Record<string, PolicyTestSuiteRunResult>>({});
  readonly testSuiteRunning = signal<Record<string, boolean>>({});

  // Import state
  readonly showImport = signal(false);
  readonly importing = signal(false);
  readonly importError = signal('');
  readonly importResult = signal<PolicyImportResponse | null>(null);
  readonly selectedFileName = signal('');
  importText = '';
  importDryRun = true;
  importOverwrite = false;

  form: PolicyForm = this.emptyForm();
  editForm: PolicyEditForm = { name: '', cedar_rule: '' };

  readonly deriveEffect = deriveEffect;
  readonly deriveAction = deriveAction;

  // Simulation state
  readonly showSimPanel = signal(false);
  readonly simulating = signal(false);
  readonly simError = signal('');
  readonly simResult = signal<SimulateResponse | null>(null);
  simForm: SimulateRequest = { agent_id: '', action: '', resource: '' };
  simContextRaw = '';

  @HostListener('document:keydown.escape')
  onEscapeKey(): void {
    if (this.showImport()) this.closeImport();
  }

  ngOnInit(): void {
    this.loadList();
    this.loadTemplates();
    this.loadTestSuites();
    if (this.route.snapshot.queryParamMap.get('onboarding') === 'sample') {
      this.openOnboardingSample();
    }
  }

  loadTemplates(): void {
    this.templatesLoading.set(true);
    this.templateError.set('');
    this.svc.listTemplates().subscribe({
      next: (templates) => {
        this.templates.set(templates);
        this.templatesLoading.set(false);
      },
      error: () => {
        this.templateError.set('Failed to load policy templates.');
        this.templatesLoading.set(false);
      },
    });
  }

  loadList(): void {
    this.loading.set(true);
    const params: import('../../services/policy.service').PolicyListParams = { limit: 200 };
    if (this.filterState) {
      params.state = this.filterState;
    } else {
      params.active = true;
    }
    if (this.searchQuery.trim()) params.search = this.searchQuery.trim();
    if (this.filterEffect) params.effect = this.filterEffect;
    this.svc.list(params).subscribe({
      next: (res) => {
        this.items.set(res);
        this.policyAnalytics.set({});
        this.policyAnalyticsLoading.set(
          Object.fromEntries(res.map((policy) => [policy.id, true]))
        );
        this.loadPolicyAnalytics(res);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  previewRule(): string {
    if (!this.form.action.trim()) return '';
    return buildCedarRule(this.form);
  }

  openCreate(): void {
    this.editingPolicy.set(null);
    this.form = this.emptyForm();
    this.formError.set('');
    this.showForm.set(true);
  }

  openOnboardingSample(): void {
    this.editingPolicy.set(null);
    this.form = {
      ...this.emptyForm(),
      name: 'Sample policy: allow web search',
      effect: 'allow',
      action: 'web_search',
    };
    this.rawCedarRule = '';
    this.formError.set('');
    this.showForm.set(true);
  }

  openEdit(p: Policy): void {
    this.showForm.set(true);
    this.editingPolicy.set(p);
    this.editForm = { name: p.name, cedar_rule: p.cedar_rule };
    this.formError.set('');
  }

  /** Holds raw Cedar text when user switches to advanced mode. */
  rawCedarRule = '';

  create(): void {
    if (!this.form.name.trim()) {
      this.formError.set('Policy name is required.');
      return;
    }
    const cedarRule = this.form.advancedMode
      ? this.rawCedarRule.trim()
      : buildCedarRule(this.form);

    if (!cedarRule) {
      this.formError.set('Cedar rule is required. Fill in Action or switch to raw editor.');
      return;
    }
    this.saving.set(true);
    this.formError.set('');
    const payload: PolicyCreate = {
      name: this.form.name.trim(),
      level: this.form.level,
      cedar_rule: cedarRule,
    };
    this.svc.create(payload).subscribe({
      next: (p) => {
        this.items.update((list) => [p, ...list]);
        this.saving.set(false);
        this.cancelForm();
      },
      error: () => {
        this.formError.set('Failed to create policy. Please try again.');
        this.saving.set(false);
      },
    });
  }

  saveEdit(): void {
    const p = this.editingPolicy();
    if (!p) return;
    if (!this.editForm.name.trim() || !this.editForm.cedar_rule.trim()) {
      this.formError.set('Name and Cedar rule are required.');
      return;
    }
    this.saving.set(true);
    this.formError.set('');
    this.svc.update(p.id, { name: this.editForm.name.trim(), cedar_rule: this.editForm.cedar_rule.trim() }).subscribe({
      next: (updated) => {
        this.items.update((list) => list.map((x) => (x.id === p.id ? updated : x)));
        this.saving.set(false);
        this.cancelForm();
      },
      error: () => {
        this.formError.set('Failed to save changes. Please try again.');
        this.saving.set(false);
      },
    });
  }

  toggle(p: Policy): void {
    this.svc.update(p.id, { active: !p.active }).subscribe({
      next: (updated) => this.items.update((list) => list.map((x) => (x.id === p.id ? updated : x))),
    });
  }

  remove(id: string): void {
    this.svc.delete(id).subscribe({
      next: () => this.items.update((list) => list.filter((x) => x.id !== id)),
      error: (err) => console.error('Failed to delete policy', err),
    });
  }

  cancelForm(): void {
    this.showForm.set(false);
    this.editingPolicy.set(null);
    this.form = this.emptyForm();
    this.editForm = { name: '', cedar_rule: '' };
    this.formError.set('');
  }

  effectVariant(cedar_rule: string): 'success' | 'danger' | 'warning' {
    const e = deriveEffect(cedar_rule);
    if (e === 'allow') return 'success';
    if (e === 'approval') return 'warning';
    return 'danger';
  }

  // --- Import / Export ---

  openImport(): void {
    this.showImport.set(true);
    this.importText = '';
    this.importDryRun = true;
    this.importOverwrite = false;
    this.importError.set('');
    this.importResult.set(null);
    this.selectedFileName.set('');
  }

  closeImport(): void {
    this.showImport.set(false);
    this.importResult.set(null);
    this.importError.set('');
    this.importText = '';
    this.selectedFileName.set('');
  }

  onOverlayClick(_event: Event): void {
    this.closeImport();
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    this.selectedFileName.set(file.name);
    const reader = new FileReader();
    reader.onload = (e) => {
      this.importText = (e.target?.result as string) ?? '';
    };
    reader.readAsText(file);
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.selectedFileName.set(file.name);
    const reader = new FileReader();
    reader.onload = (e) => {
      this.importText = (e.target?.result as string) ?? '';
    };
    reader.readAsText(file);
  }

  runImport(): void {
    const raw = this.importText.trim();
    if (!raw) {
      this.importError.set('Paste or upload a JSON / YAML file first.');
      return;
    }
    this.importError.set('');
    this.importResult.set(null);
    this.importing.set(true);

    let body: object;
    try {
      body = JSON.parse(raw);
    } catch {
      this.importError.set('Invalid JSON. Check your input and try again.');
      this.importing.set(false);
      return;
    }

    const req = {
      ...(body as object),
      dry_run: this.importDryRun,
      overwrite: this.importOverwrite,
    };

    this.svc.importPolicies(req as Parameters<PolicyService['importPolicies']>[0]).subscribe({
      next: (res) => {
        this.importResult.set(res);
        this.importing.set(false);
        // If not a dry run and no errors, reload the list
        if (!res.dry_run && res.errors === 0) {
          this.loadList();
        }
      },
      error: (err) => {
        const msg = err?.error?.detail ?? err?.error?.message ?? 'Import failed. Check your file and try again.';
        this.importError.set(msg);
        this.importing.set(false);
      },
    });
  }

  confirmImport(): void {
    this.importDryRun = false;
    this.importResult.set(null);
    this.runImport();
  }

  exportAll(): void {
    this.svc.exportPolicies().subscribe({
      next: (policies) => {
        const date = new Date().toISOString().split('T')[0];
        const payload = JSON.stringify({ policies }, null, 2);
        const blob = new Blob([payload], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `agr_policies_${date}.json`;
        a.click();
        URL.revokeObjectURL(url);
      },
    });
  }

  downloadSample(): void {
    const blob = new Blob([SAMPLE_POLICIES_JSON], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'agr_policies_sample.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  statusBadgeClass(status: PolicyImportResult['status']): string {
    const map: Record<string, string> = {
      created: 'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/15 text-emerald-400',
      updated: 'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-500/15 text-amber-400',
      skipped: 'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-700 text-slate-400',
      error: 'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-500/15 text-red-400',
    };
    return map[status] ?? map['skipped'];
  }

  importTemplate(template: PolicyTemplate): void {
    this.templateActionMessage.set('');
    this.templateError.set('');
    this.svc.importPolicies({ policies: template.policies, dry_run: false, overwrite: false }).subscribe({
      next: (res) => {
        this.templateActionMessage.set(
          `${template.name}: ${res.created} created, ${res.updated} updated, ${res.skipped} skipped.`,
        );
        this.loadList();
      },
      error: (err) => {
        const msg = err?.error?.detail ?? err?.error?.message ?? `Failed to import ${template.name}.`;
        this.templateError.set(msg);
      },
    });
  }

  // --- Simulation ---

  loadTestSuites(): void {
    this.testSuitesLoading.set(true);
    this.testSuiteError.set('');
    this.svc.listTestSuites().subscribe({
      next: (suites) => {
        this.testSuites.set(suites);
        this.testSuitesLoading.set(false);
      },
      error: () => {
        this.testSuitesLoading.set(false);
        this.testSuiteError.set('Policy test suites are not available right now.');
      },
    });
  }

  runTestSuite(suiteId: string): void {
    this.testSuiteRunning.update((state) => ({ ...state, [suiteId]: true }));
    this.testSuiteError.set('');
    this.svc.runTestSuite(suiteId).subscribe({
      next: (result) => {
        this.testSuiteRunning.update((state) => ({ ...state, [suiteId]: false }));
        this.testSuiteRuns.update((state) => ({ ...state, [suiteId]: result }));
      },
      error: () => {
        this.testSuiteRunning.update((state) => ({ ...state, [suiteId]: false }));
        this.testSuiteError.set('Unable to run the selected policy test suite.');
      },
    });
  }

  lastTestCaseResult(suiteId: string, caseName: string): PolicyTestCaseResult | null {
    return this.testSuiteRuns()[suiteId]?.results.find((result) => result.name === caseName) ?? null;
  }

  toggleSimPanel(): void {
    this.showSimPanel.update((v) => !v);
    if (!this.showSimPanel()) {
      this.simResult.set(null);
      this.simError.set('');
    }
  }

  runSimulation(): void {
    if (!this.simForm.agent_id.trim() || !this.simForm.action.trim() || !this.simForm.resource.trim()) {
      this.simError.set('Agent ID, action, and resource are required.');
      return;
    }

    let context: Record<string, unknown> | undefined;
    if (this.simContextRaw.trim()) {
      try {
        context = JSON.parse(this.simContextRaw.trim());
      } catch {
        this.simError.set('Context must be valid JSON.');
        return;
      }
    }

    this.simError.set('');
    this.simResult.set(null);
    this.simulating.set(true);

    const req: SimulateRequest = {
      agent_id: this.simForm.agent_id.trim(),
      action: this.simForm.action.trim(),
      resource: this.simForm.resource.trim(),
      ...(context ? { context } : {}),
    };

    this.svc.simulate(req).subscribe({
      next: (res) => {
        this.simResult.set(res);
        this.simulating.set(false);
      },
      error: (err) => {
        const msg = err?.error?.detail ?? err?.error?.message ?? 'Simulation failed. Check your inputs and try again.';
        this.simError.set(msg);
        this.simulating.set(false);
      },
    });
  }

  simDecisionBg(decision: string): string {
    if (decision === 'ALLOW') return 'bg-emerald-500/10 border-b border-emerald-500/20';
    if (decision === 'DENY') return 'bg-red-500/10 border-b border-red-500/20';
    return 'bg-amber-500/10 border-b border-amber-500/20';
  }

  simDecisionBadgeClass(decision: string): string {
    if (decision === 'ALLOW') return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40';
    if (decision === 'DENY') return 'bg-red-500/20 text-red-400 border-red-500/40';
    return 'bg-amber-500/20 text-amber-400 border-amber-500/40';
  }

  private loadPolicyAnalytics(policies: Policy[]): void {
    if (policies.length === 0) {
      this.policyAnalytics.set({});
      this.policyAnalyticsLoading.set({});
      return;
    }

    this.svc.getAnalytics(true).subscribe({
      next: (rows) => {
        const rowsById = Object.fromEntries(
          rows.map((row) => [row.policy_id, this.mapAnalyticsRow(row)])
        );
        this.policyAnalytics.set(
          Object.fromEntries(
            policies.map((policy) => [policy.id, rowsById[policy.id] ?? this.emptyAnalytics()])
          )
        );
        this.policyAnalyticsLoading.set(
          Object.fromEntries(policies.map((policy) => [policy.id, false]))
        );
      },
      error: () => {
        this.policyAnalytics.set(
          Object.fromEntries(policies.map((policy) => [policy.id, null]))
        );
        this.policyAnalyticsLoading.set(
          Object.fromEntries(policies.map((policy) => [policy.id, false]))
        );
      },
    });
  }

  private mapAnalyticsRow(row: PolicyAnalyticsSummary): PolicyAnalytics {
    return {
      totalEvaluations: row.total_evaluations,
      lastTriggeredAt: row.last_triggered_at,
      decisions: {
        ALLOW: row.decisions.ALLOW,
        DENY: row.decisions.DENY,
        APPROVAL_REQUIRED: row.decisions.APPROVAL_REQUIRED,
      },
    };
  }

  private emptyAnalytics(): PolicyAnalytics {
    return {
      totalEvaluations: 0,
      lastTriggeredAt: null,
      decisions: {
        ALLOW: 0,
        DENY: 0,
        APPROVAL_REQUIRED: 0,
      },
    };
  }

  readonly builderTemplates = BUILDER_TEMPLATES;

  applyBuilderTemplate(tpl: Partial<PolicyForm>): void {
    this.form = { ...this.emptyForm(), ...tpl };
    this.rawCedarRule = '';
  }

  get previewCedarRule(): string {
    if (!this.form.action.trim()) return '// fill in Action above to see preview';
    return buildCedarRule(this.form);
  }

  private emptyForm(): PolicyForm {
    return {
      name: '',
      effect: 'allow',
      action: '',
      resource_attr: '',
      resource_value: '',
      context_attr: '',
      context_op: '==',
      context_value: '',
      threshold_attr: '',
      threshold_op: '>',
      threshold_value: '',
      level: 'org',
      advancedMode: false,
    };
  }
}
