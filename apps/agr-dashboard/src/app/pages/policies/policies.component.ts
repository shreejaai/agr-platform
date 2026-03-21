import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { PolicyService, PolicyImportResponse, PolicyImportResult } from '../../services/policy.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { Policy, PolicyCreate } from '../../core/models/policy.model';

/** Friendly form fields — converted to PolicyCreate (cedar_rule) on submit. */
interface PolicyForm {
  name: string;
  effect: 'allow' | 'deny' | 'require_approval';
  action: string;
  resource_attr: string;
  resource_value: string;
  level: 'org' | 'project' | 'agent';
}

interface PolicyEditForm {
  name: string;
  cedar_rule: string;
}

/** Generate a Cedar rule string from friendly form fields. */
function buildCedarRule(form: PolicyForm): string {
  const action = form.action.trim();

  if (form.effect === 'require_approval') {
    let rule = `forbid(principal, action == Action::"${action}", resource)`;
    if (form.resource_attr.trim() && form.resource_value.trim()) {
      rule += `\nwhen { resource has ${form.resource_attr} && resource.${form.resource_attr} == "${form.resource_value}" }`;
    }
    rule += '\nunless { context has approval_status && context.approval_status == "approved" };';
    return rule;
  }

  const kw = form.effect === 'allow' ? 'permit' : 'forbid';
  let rule = `${kw}(principal, action == Action::"${action}", resource)`;
  if (form.resource_attr.trim() && form.resource_value.trim()) {
    rule += `\nwhen { resource has ${form.resource_attr} && resource.${form.resource_attr} == "${form.resource_value}" };`;
  } else {
    rule += ';';
  }
  return rule;
}

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
  imports: [FormsModule, BadgeComponent],
  template: `
    <div class="space-y-4">
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

      <!-- Import panel -->
      @if (showImport()) {
        <div class="card border border-sky-500/30 space-y-4">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold text-slate-100">Import Policies</h2>
            <button (click)="downloadSample()" class="text-xs text-sky-400 hover:text-sky-300 underline transition-colors">
              Download sample JSON
            </button>
          </div>

          <p class="text-xs text-slate-400">
            Paste a JSON object with a <code class="bg-slate-800 px-1 rounded">policies</code> array, or upload a
            <code class="bg-slate-800 px-1 rounded">.json</code> file.
            Supports three formats: JSON object, YAML, or raw Cedar rules (blank-line separated).
          </p>

          <!-- File upload -->
          <div>
            <label class="block text-xs text-slate-400 mb-1">Upload file (.json / .yaml / .cedar)</label>
            <input
              type="file"
              accept=".json,.yaml,.yml,.cedar,.txt"
              (change)="onFileSelected($event)"
              class="block text-xs text-slate-300 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0
                     file:text-xs file:bg-slate-700 file:text-slate-200 hover:file:bg-slate-600 cursor-pointer"
            />
          </div>

          <!-- Paste area -->
          <div>
            <label class="block text-xs text-slate-400 mb-1">Or paste JSON / YAML content</label>
            <textarea
              [(ngModel)]="importText"
              class="input w-full font-mono text-xs"
              rows="8"
              placeholder="{{ samplePlaceholder }}"
            ></textarea>
          </div>

          <!-- Options -->
          <div class="flex items-center gap-6 text-sm">
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" [(ngModel)]="importDryRun" class="rounded" />
              <span class="text-slate-300">Dry run <span class="text-slate-500 text-xs">(preview without saving)</span></span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" [(ngModel)]="importOverwrite" class="rounded" />
              <span class="text-slate-300">Overwrite duplicates</span>
            </label>
          </div>

          @if (importError()) {
            <p class="text-sm text-red-400">{{ importError() }}</p>
          }

          <!-- Dry run preview results -->
          @if (importResult()) {
            <div class="rounded border border-slate-700 overflow-hidden text-xs">
              <div class="px-3 py-2 bg-slate-800 flex items-center gap-4 text-slate-300">
                <span>Total: <strong>{{ importResult()!.total }}</strong></span>
                <span class="text-emerald-400">Created: {{ importResult()!.created }}</span>
                <span class="text-amber-400">Updated: {{ importResult()!.updated }}</span>
                <span class="text-slate-400">Skipped: {{ importResult()!.skipped }}</span>
                @if (importResult()!.errors > 0) {
                  <span class="text-red-400">Errors: {{ importResult()!.errors }}</span>
                }
                @if (importResult()!.dry_run) {
                  <span class="ml-auto text-sky-400 font-medium">DRY RUN — nothing was saved</span>
                }
              </div>
              <table class="w-full">
                @for (r of importResult()!.results; track r.name) {
                  <tr class="border-t border-slate-700/50">
                    <td class="px-3 py-1.5 text-slate-300">{{ r.name }}</td>
                    <td class="px-3 py-1.5">
                      <span [class]="statusClass(r.status)">{{ r.status }}</span>
                    </td>
                    <td class="px-3 py-1.5 text-slate-500">{{ r.error ?? '' }}</td>
                  </tr>
                }
              </table>
            </div>
          }

          <div class="flex gap-2">
            <button
              (click)="runImport()"
              [disabled]="importing()"
              class="btn-primary text-sm"
            >
              {{ importing() ? 'Importing…' : (importDryRun ? 'Preview' : 'Import') }}
            </button>
            <button
              (click)="closeImport()"
              class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors"
            >Cancel</button>
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

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="policy-effect" class="block text-xs text-slate-400 mb-1">Effect</label>
                <select id="policy-effect" [(ngModel)]="form.effect" class="input w-full">
                  <option value="allow">Allow</option>
                  <option value="deny">Deny</option>
                  <option value="require_approval">Require approval</option>
                </select>
              </div>
              <div>
                <label for="policy-action" class="block text-xs text-slate-400 mb-1">Action (tool name)</label>
                <input id="policy-action" [(ngModel)]="form.action" class="input w-full" placeholder="web_search" />
              </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="policy-resource-attr" class="block text-xs text-slate-400 mb-1">When resource has attribute</label>
                <input id="policy-resource-attr" [(ngModel)]="form.resource_attr" class="input w-full" placeholder="environment (optional)" />
              </div>
              <div>
                <label for="policy-resource-value" class="block text-xs text-slate-400 mb-1">equals value</label>
                <input id="policy-resource-value" [(ngModel)]="form.resource_value" class="input w-full" placeholder="production (optional)" />
              </div>
            </div>

            @if (previewRule()) {
              <div>
                <p class="block text-xs text-slate-400 mb-1">Generated Cedar rule</p>
                <pre class="text-xs bg-slate-900 rounded p-2 text-indigo-300 overflow-x-auto">{{ previewRule() }}</pre>
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

      <!-- List -->
      @if (loading()) {
        <div class="py-16 text-center text-slate-500 text-sm">Loading…</div>
      } @else if (items().length === 0) {
        <div class="card py-16 text-center">
          <p class="text-slate-400">No policies yet.</p>
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
                  <td class="table-cell font-medium text-slate-200">{{ p.name }}</td>
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
    </div>
  `,
})
export class PoliciesComponent implements OnInit {
  private svc = inject(PolicyService);

  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly showForm = signal(false);
  readonly formError = signal('');
  readonly items = signal<Policy[]>([]);
  readonly editingPolicy = signal<Policy | null>(null);

  // Import state
  readonly showImport = signal(false);
  readonly importing = signal(false);
  readonly importError = signal('');
  readonly importResult = signal<PolicyImportResponse | null>(null);
  importText = '';
  importDryRun = false;
  importOverwrite = false;

  readonly samplePlaceholder = `{
  "policies": [
    {
      "name": "allow-web-search",
      "level": "org",
      "cedar_rule": "permit(principal, action == Action::\\"web_search\\", resource);"
    }
  ]
}`;

  form: PolicyForm = this.emptyForm();
  editForm: PolicyEditForm = { name: '', cedar_rule: '' };

  readonly deriveEffect = deriveEffect;
  readonly deriveAction = deriveAction;

  ngOnInit(): void {
    this.loadList();
  }

  loadList(): void {
    this.svc.list({ limit: 100 }).subscribe({
      next: (res) => {
        this.items.set(res);
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

  openEdit(p: Policy): void {
    this.showForm.set(true);
    this.editingPolicy.set(p);
    this.editForm = { name: p.name, cedar_rule: p.cedar_rule };
    this.formError.set('');
  }

  create(): void {
    if (!this.form.name.trim() || !this.form.action.trim()) {
      this.formError.set('Name and action are required.');
      return;
    }
    this.saving.set(true);
    this.formError.set('');
    const payload: PolicyCreate = {
      name: this.form.name.trim(),
      level: this.form.level,
      cedar_rule: buildCedarRule(this.form),
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
    this.importDryRun = false;
    this.importOverwrite = false;
    this.importError.set('');
    this.importResult.set(null);
  }

  closeImport(): void {
    this.showImport.set(false);
    this.importResult.set(null);
    this.importError.set('');
    this.importText = '';
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
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

  exportAll(): void {
    this.svc.exportPolicies().subscribe({
      next: (policies) => {
        const payload = JSON.stringify({ policies }, null, 2);
        const blob = new Blob([payload], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'agr_policies_export.json';
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

  statusClass(status: PolicyImportResult['status']): string {
    const map: Record<string, string> = {
      created: 'text-emerald-400',
      updated: 'text-amber-400',
      skipped: 'text-slate-400',
      error: 'text-red-400',
    };
    return map[status] ?? 'text-slate-400';
  }

  private emptyForm(): PolicyForm {
    return { name: '', effect: 'allow', action: '', resource_attr: '', resource_value: '', level: 'org' };
  }
}
