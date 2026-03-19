import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { PolicyService } from '../../services/policy.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { Policy, PolicyCreate } from '../../models/policy.model';

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
          <p class="text-sm text-slate-400 mt-1">Manage Cedar-based governance rules for your agents.</p>
        </div>
        <button (click)="showForm.set(true)" class="btn-primary text-sm">+ New policy</button>
      </div>

      <!-- Create form -->
      @if (showForm()) {
        <div class="card border border-indigo-500/30">
          <h2 class="text-base font-semibold text-slate-100 mb-4">New Policy</h2>
          <div class="space-y-3">
            <div>
              <label class="block text-xs text-slate-400 mb-1">Name</label>
              <input [(ngModel)]="form.name" class="input w-full" placeholder="allow-web-search" />
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Description</label>
              <input [(ngModel)]="form.description" class="input w-full"
                     placeholder="Allows agents to call web_search tool" />
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Effect</label>
              <select [(ngModel)]="form.effect" class="input w-full">
                <option value="allow">allow</option>
                <option value="deny">deny</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Action (tool name or glob)</label>
              <input [(ngModel)]="form.action" class="input w-full" placeholder="web_search" />
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Resource (optional)</label>
              <input [(ngModel)]="form.resource" class="input w-full" placeholder="*" />
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Conditions JSON (optional)</label>
              <textarea [(ngModel)]="form.conditions" rows="3"
                        class="input w-full font-mono text-xs resize-y"
                        placeholder='{"max_tokens": 1000}'></textarea>
            </div>

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
                <th class="table-header">Resource</th>
                <th class="table-header">Status</th>
                <th class="table-header"></th>
              </tr>
            </thead>
            <tbody>
              @for (p of items(); track p.id) {
                <tr class="table-row">
                  <td class="table-cell font-medium text-slate-200">
                    <div>{{ p.name }}</div>
                    @if (p.description) {
                      <div class="text-xs text-slate-500 font-normal">{{ p.description }}</div>
                    }
                  </td>
                  <td class="table-cell">
                    <agr-badge [variant]="p.effect === 'allow' ? 'success' : 'danger'">
                      {{ p.effect }}
                    </agr-badge>
                  </td>
                  <td class="table-cell font-mono text-xs text-slate-300">{{ p.action }}</td>
                  <td class="table-cell font-mono text-xs text-slate-400">{{ p.resource ?? '*' }}</td>
                  <td class="table-cell">
                    <agr-badge [variant]="p.enabled ? 'success' : 'neutral'">
                      {{ p.enabled ? 'enabled' : 'disabled' }}
                    </agr-badge>
                  </td>
                  <td class="table-cell text-right">
                    <button
                      (click)="toggle(p)"
                      class="text-xs text-slate-500 hover:text-slate-200 mr-3 transition-colors"
                    >
                      {{ p.enabled ? 'Disable' : 'Enable' }}
                    </button>
                    <button
                      (click)="remove(p.id)"
                      class="text-xs text-red-500/70 hover:text-red-400 transition-colors"
                    >
                      Delete
                    </button>
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

  form: PolicyCreate & { conditions: string } = this.emptyForm();

  ngOnInit(): void {
    this.loadList();
  }

  loadList(): void {
    this.svc.list({ limit: 100 }).subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  create(): void {
    if (!this.form.name.trim() || !this.form.action.trim()) {
      this.formError.set('Name and action are required.');
      return;
    }
    let conditions: Record<string, unknown> | undefined;
    if (this.form.conditions.trim()) {
      try {
        conditions = JSON.parse(this.form.conditions);
      } catch {
        this.formError.set('Conditions must be valid JSON.');
        return;
      }
    }
    this.saving.set(true);
    this.formError.set('');
    const payload: PolicyCreate = {
      name: this.form.name.trim(),
      description: this.form.description.trim() || undefined,
      effect: this.form.effect,
      action: this.form.action.trim(),
      resource: this.form.resource.trim() || undefined,
      conditions,
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

  toggle(p: Policy): void {
    this.svc.update(p.id, { enabled: !p.enabled }).subscribe({
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
    this.form = this.emptyForm();
    this.formError.set('');
  }

  private emptyForm(): PolicyCreate & { conditions: string } {
    return { name: '', description: '', effect: 'allow', action: '', resource: '', conditions: '' };
  }
}
