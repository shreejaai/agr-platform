import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { PolicyService } from '../../services/policy.service';
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
        <button (click)="openCreate()" class="btn-primary text-sm">+ New policy</button>
      </div>

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

  private emptyForm(): PolicyForm {
    return { name: '', effect: 'allow', action: '', resource_attr: '', resource_value: '', level: 'org' };
  }
}
