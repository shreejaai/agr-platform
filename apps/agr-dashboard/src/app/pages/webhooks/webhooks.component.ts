import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { WebhookService } from '../../services/webhook.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { Webhook, WebhookCreate } from '../../models/webhook.model';

const AVAILABLE_EVENTS = [
  'tool.allow', 'tool.deny', 'approval.requested', 'approval.approved', 'approval.rejected',
];

@Component({
  selector: 'agr-webhooks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, BadgeComponent, RelativeTimePipe],
  template: `
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-slate-100">Webhooks</h1>
          <p class="text-sm text-slate-400 mt-1">Push governance events to your systems via HMAC-signed HTTP.</p>
        </div>
        <button (click)="showForm.set(true)" class="btn-primary text-sm">+ New webhook</button>
      </div>

      <!-- Create form -->
      @if (showForm()) {
        <div class="card border border-indigo-500/30">
          <h2 class="text-base font-semibold text-slate-100 mb-4">New Webhook</h2>
          <div class="space-y-3">
            <div>
              <label class="block text-xs text-slate-400 mb-1">Endpoint URL</label>
              <input [(ngModel)]="form.url" class="input w-full font-mono text-sm"
                     placeholder="https://your-server.com/agr-events" type="url" />
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-2">Events to subscribe</label>
              <div class="grid grid-cols-2 gap-2">
                @for (evt of availableEvents; track evt) {
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      [checked]="form.events.includes(evt)"
                      (change)="toggleEvent(evt)"
                      class="w-3.5 h-3.5 accent-indigo-500"
                    />
                    <span class="text-xs font-mono text-slate-300">{{ evt }}</span>
                  </label>
                }
              </div>
            </div>

            @if (formError()) {
              <p class="text-sm text-red-400">{{ formError() }}</p>
            }
            @if (createdSecret()) {
              <div class="p-3 rounded-lg bg-green-500/10 border border-green-500/20">
                <p class="text-xs text-green-400 mb-1 font-medium">Webhook created! Save your signing secret — it won't be shown again.</p>
                <code class="text-xs font-mono text-slate-200 break-all">{{ createdSecret() }}</code>
              </div>
            }

            <div class="flex gap-2">
              <button (click)="create()" [disabled]="saving()" class="btn-primary text-sm">
                {{ saving() ? 'Creating…' : 'Create webhook' }}
              </button>
              <button (click)="cancelForm()"
                      class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors">
                {{ createdSecret() ? 'Done' : 'Cancel' }}
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
          <p class="text-slate-400">No webhooks configured.</p>
          <p class="text-slate-500 text-xs mt-1">Add a webhook endpoint to receive real-time governance events.</p>
        </div>
      } @else {
        <div class="space-y-3">
          @for (w of items(); track w.id) {
            <div class="card">
              <div class="flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-1">
                    <agr-badge [variant]="w.enabled ? 'success' : 'neutral'">
                      {{ w.enabled ? 'active' : 'disabled' }}
                    </agr-badge>
                    <span class="text-xs text-slate-500">{{ w.created_at | relativeTime }}</span>
                  </div>
                  <p class="text-sm font-mono text-slate-200 truncate">{{ w.url }}</p>
                  <div class="flex flex-wrap gap-1 mt-2">
                    @for (evt of w.events; track evt) {
                      <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                        {{ evt }}
                      </span>
                    }
                  </div>
                </div>
                <button
                  (click)="remove(w.id)"
                  class="text-xs text-red-500/70 hover:text-red-400 shrink-0 transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class WebhooksComponent implements OnInit {
  private svc = inject(WebhookService);

  readonly availableEvents = AVAILABLE_EVENTS;
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly showForm = signal(false);
  readonly formError = signal('');
  readonly createdSecret = signal('');
  readonly items = signal<Webhook[]>([]);

  form: WebhookCreate = this.emptyForm();

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

  toggleEvent(evt: string): void {
    if (this.form.events.includes(evt)) {
      this.form = { ...this.form, events: this.form.events.filter((e) => e !== evt) };
    } else {
      this.form = { ...this.form, events: [...this.form.events, evt] };
    }
  }

  create(): void {
    if (!this.form.url.trim()) {
      this.formError.set('Endpoint URL is required.');
      return;
    }
    if (this.form.events.length === 0) {
      this.formError.set('Select at least one event.');
      return;
    }
    this.saving.set(true);
    this.formError.set('');
    this.svc.create(this.form).subscribe({
      next: (res) => {
        this.saving.set(false);
        if (res.secret) {
          this.createdSecret.set(res.secret);
        }
        this.loadList();
      },
      error: () => {
        this.formError.set('Failed to create webhook. Please try again.');
        this.saving.set(false);
      },
    });
  }

  remove(id: string): void {
    this.svc.delete(id).subscribe({
      next: () => this.items.update((list) => list.filter((w) => w.id !== id)),
    });
  }

  cancelForm(): void {
    this.showForm.set(false);
    this.form = this.emptyForm();
    this.formError.set('');
    this.createdSecret.set('');
  }

  private emptyForm(): WebhookCreate {
    return { url: '', events: [] };
  }
}
