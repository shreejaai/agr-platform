import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { JsonPipe, NgClass, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { OrgService } from '../../services/org.service';
import { WebhookService } from '../../services/webhook.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import {
  Webhook,
  WebhookCreate,
  WebhookDelivery,
  WebhookEvent,
  WebhookUpdate,
} from '../../core/models/webhook.model';

const AVAILABLE_EVENTS: WebhookEvent[] = ['approval.approved', 'approval.rejected'];

@Component({
  selector: 'agr-webhooks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, JsonPipe, NgClass, NgIf, BadgeComponent, RelativeTimePipe],
  template: `
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-slate-100">Webhooks</h1>
          <p class="text-sm text-slate-400 mt-1">
            Push approval events to your systems via HMAC-signed HTTP.
          </p>
        </div>
        <button (click)="openCreate()" class="btn-primary text-sm">+ New webhook</button>
      </div>

      @if (!canRetryDeliveries()) {
        <div class="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          Delivery retry is admin-only. You can still inspect delivery history and payloads.
        </div>
      }

      @if (showForm() && !editingWebhook()) {
        <div class="card border border-indigo-500/30">
          <h2 class="text-base font-semibold text-slate-100 mb-4">New Webhook</h2>
          <div class="space-y-3">
            <div>
              <label for="webhook-url" class="block text-xs text-slate-400 mb-1">Endpoint URL</label>
              <input id="webhook-url" [(ngModel)]="formUrl" class="input w-full font-mono text-sm"
                     placeholder="https://your-server.com/agr-events" type="url" />
            </div>
            <div>
              <p class="block text-xs text-slate-400 mb-2">Events to subscribe</p>
              <div class="flex gap-4">
                @for (evt of availableEvents; track evt) {
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      [checked]="formEvents.includes(evt)"
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
                <p class="text-xs text-green-400 mb-1 font-medium">
                  Webhook created. Save your signing secret - it will not be shown again.
                </p>
                <code class="text-xs font-mono text-slate-200 break-all select-all">{{ createdSecret() }}</code>
              </div>
            }

            <div class="flex gap-2">
              <button (click)="create()" [disabled]="saving()" class="btn-primary text-sm">
                {{ saving() ? 'Creating...' : 'Create webhook' }}
              </button>
              <button (click)="cancelForm()"
                      class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors">
                {{ createdSecret() ? 'Done' : 'Cancel' }}
              </button>
            </div>
          </div>
        </div>
      }

      @if (editingWebhook()) {
        <div class="card border border-amber-500/30">
          <h2 class="text-base font-semibold text-slate-100 mb-4">Edit Webhook</h2>
          <div class="space-y-3">
            <div>
              <label for="edit-webhook-url" class="block text-xs text-slate-400 mb-1">Endpoint URL</label>
              <input id="edit-webhook-url" [(ngModel)]="editUrl" class="input w-full font-mono text-sm" type="url" />
            </div>
            <div>
              <p class="block text-xs text-slate-400 mb-2">Events to subscribe</p>
              <div class="flex gap-4">
                @for (evt of availableEvents; track evt) {
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      [checked]="editEvents.includes(evt)"
                      (change)="toggleEditEvent(evt)"
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

            <div class="flex gap-2">
              <button (click)="saveEdit()" [disabled]="saving()" class="btn-primary text-sm">
                {{ saving() ? 'Saving...' : 'Save changes' }}
              </button>
              <button (click)="cancelForm()"
                      class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors">
                Cancel
              </button>
            </div>
          </div>
        </div>
      }

      <div class="card bg-slate-900/50">
        <h2 class="text-xs font-semibold text-slate-400 mb-2">Verifying signatures</h2>
        <pre class="text-xs font-mono text-slate-400 overflow-x-auto">X-AGR-Signature: t=&#123;timestamp&#125;,v1=&#123;hmac_hex&#125;
Signed content:  "&#123;timestamp&#125;.&#123;json_body&#125;"</pre>
      </div>

      @if (loading()) {
        <div class="py-8 text-center text-slate-500 text-sm">Loading...</div>
      } @else if (items().length === 0) {
        <div class="card py-16 text-center">
          <p class="text-slate-400">No webhooks configured.</p>
          <p class="text-slate-500 text-xs mt-1">
            Add a webhook endpoint to receive real-time governance events.
          </p>
        </div>
      } @else {
        <div class="space-y-3">
          @for (webhook of items(); track webhook.id) {
            <div class="card">
              <div class="flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-1">
                    <agr-badge [variant]="webhook.active ? 'success' : 'neutral'">
                      {{ webhook.active ? 'active' : 'disabled' }}
                    </agr-badge>
                    <span class="text-xs text-slate-500">{{ webhook.created_at | relativeTime }}</span>
                  </div>
                  <p class="text-sm font-mono text-slate-200 truncate">{{ webhook.url }}</p>
                  <div class="flex flex-wrap gap-1 mt-2">
                    @for (evt of webhook.events; track evt) {
                      <span class="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                        {{ evt }}
                      </span>
                    }
                  </div>
                </div>
                <div class="flex items-center gap-3 shrink-0">
                  <button
                    (click)="toggleDeliveries(webhook.id)"
                    class="text-xs text-slate-500 hover:text-slate-200 transition-colors"
                  >
                    {{ expandedWebhookId() === webhook.id ? 'Hide deliveries' : 'View deliveries' }}
                  </button>
                  <button
                    (click)="openEdit(webhook)"
                    class="text-xs text-slate-500 hover:text-slate-200 transition-colors"
                  >Edit</button>
                  <button
                    (click)="toggleActive(webhook)"
                    class="text-xs text-slate-500 hover:text-slate-200 transition-colors"
                  >{{ webhook.active ? 'Disable' : 'Enable' }}</button>
                  <button
                    (click)="remove(webhook.id)"
                    class="text-xs text-red-500/70 hover:text-red-400 transition-colors"
                  >Delete</button>
                </div>
              </div>

              @if (expandedWebhookId() === webhook.id) {
                <div class="mt-4 border-t border-slate-800 pt-4 space-y-3">
                  <div class="flex items-center justify-between gap-4">
                    <div>
                      <h3 class="text-sm font-semibold text-slate-100">Delivery history</h3>
                      <p class="text-xs text-slate-500 mt-1">
                        Last 50 attempts, newest first. Retry creates a new delivery record.
                      </p>
                    </div>
                    @if (deliveriesLoadingFor(webhook.id)) {
                      <span class="text-xs text-slate-500">Loading deliveries...</span>
                    }
                  </div>

                  @if (deliveriesErrorFor(webhook.id)) {
                    <div class="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                      {{ deliveriesErrorFor(webhook.id) }}
                    </div>
                  } @else if (deliveriesFor(webhook.id).length === 0) {
                    <div class="rounded-lg border border-slate-800 bg-slate-950/50 px-4 py-4 text-sm text-slate-500">
                      No deliveries have been recorded for this webhook yet.
                    </div>
                  } @else {
                    <div class="space-y-3">
                      @for (delivery of deliveriesFor(webhook.id); track delivery.id) {
                        <div class="rounded-lg border border-slate-800 bg-slate-950/60 px-4 py-4 space-y-3">
                          <div class="flex items-start justify-between gap-4">
                            <div class="min-w-0">
                              <div class="flex items-center gap-2 flex-wrap">
                                <agr-badge [variant]="deliveryStatusVariant(delivery.status)">
                                  {{ delivery.status }}
                                </agr-badge>
                                <span class="text-xs text-slate-500">{{ delivery.created_at | relativeTime }}</span>
                                @if (delivery.http_status !== null) {
                                  <span class="text-xs font-mono text-slate-400">
                                    HTTP {{ delivery.http_status }}
                                  </span>
                                }
                                <span class="text-xs font-mono text-slate-500">
                                  attempt {{ delivery.attempts }}
                                </span>
                              </div>
                              <p class="mt-2 text-sm font-mono text-slate-200">{{ delivery.event }}</p>
                            </div>

                            @if (delivery.status === 'failed') {
                              @if (canRetryDeliveries()) {
                                <button
                                  type="button"
                                  (click)="retryDelivery(webhook.id, delivery.id)"
                                  [disabled]="retryingDeliveryId() === delivery.id"
                                  class="px-3 py-1.5 text-xs font-medium rounded-lg
                                         bg-amber-500/15 text-amber-300 border border-amber-500/30
                                         hover:bg-amber-500/25 transition-colors disabled:opacity-50"
                                >
                                  {{ retryingDeliveryId() === delivery.id ? 'Retrying...' : 'Retry delivery' }}
                                </button>
                              } @else {
                                <span class="text-xs text-slate-500">Admin only</span>
                              }
                            }
                          </div>

                          <div class="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
                            <div class="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-3">
                              <p class="text-xs uppercase tracking-wide text-slate-500">Response preview</p>
                              @if (delivery.last_error) {
                                <pre class="mt-2 whitespace-pre-wrap text-xs text-red-200">{{ delivery.last_error }}</pre>
                              } @else if (delivery.http_status !== null) {
                                <p class="mt-2 text-xs text-slate-300">
                                  HTTP {{ delivery.http_status }}
                                  {{ delivery.status === 'success' ? 'returned successfully.' : 'returned without an error body.' }}
                                </p>
                              } @else {
                                <p class="mt-2 text-xs text-slate-500">No response body captured for this attempt.</p>
                              }
                            </div>

                            <details class="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-3">
                              <summary class="cursor-pointer text-xs font-medium text-slate-300 hover:text-slate-100">
                                Delivery payload
                              </summary>
                              <pre class="mt-3 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-300">{{ delivery.payload | json }}</pre>
                            </details>
                          </div>
                        </div>
                      }
                    </div>
                  }
                </div>
              }
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class WebhooksComponent implements OnInit {
  private readonly orgSvc = inject(OrgService);
  private readonly svc = inject(WebhookService);

  readonly availableEvents = AVAILABLE_EVENTS;
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly showForm = signal(false);
  readonly formError = signal('');
  readonly createdSecret = signal('');
  readonly items = signal<Webhook[]>([]);
  readonly editingWebhook = signal<Webhook | null>(null);
  readonly expandedWebhookId = signal<string | null>(null);
  readonly deliveriesMap = signal<Record<string, WebhookDelivery[]>>({});
  readonly deliveriesLoadingMap = signal<Record<string, boolean>>({});
  readonly deliveriesErrorMap = signal<Record<string, string>>({});
  readonly orgRole = signal<'admin' | 'operator' | 'viewer'>('viewer');
  readonly retryingDeliveryId = signal<string | null>(null);
  readonly canRetryDeliveries = computed(() => this.orgRole() === 'admin');

  formUrl = '';
  formEvents: WebhookEvent[] = [...AVAILABLE_EVENTS];
  editUrl = '';
  editEvents: WebhookEvent[] = [...AVAILABLE_EVENTS];

  ngOnInit(): void {
    this.loadRole();
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

  toggleDeliveries(webhookId: string): void {
    const isExpanded = this.expandedWebhookId() === webhookId;
    this.expandedWebhookId.set(isExpanded ? null : webhookId);
    if (!isExpanded && this.deliveriesFor(webhookId).length === 0 && !this.deliveriesLoadingFor(webhookId)) {
      this.loadDeliveries(webhookId);
    }
  }

  deliveriesFor(webhookId: string): WebhookDelivery[] {
    return this.deliveriesMap()[webhookId] ?? [];
  }

  deliveriesLoadingFor(webhookId: string): boolean {
    return this.deliveriesLoadingMap()[webhookId] ?? false;
  }

  deliveriesErrorFor(webhookId: string): string | null {
    return this.deliveriesErrorMap()[webhookId] ?? null;
  }

  openCreate(): void {
    this.editingWebhook.set(null);
    this.formUrl = '';
    this.formEvents = [...AVAILABLE_EVENTS];
    this.formError.set('');
    this.createdSecret.set('');
    this.showForm.set(true);
  }

  openEdit(webhook: Webhook): void {
    this.editingWebhook.set(webhook);
    this.editUrl = webhook.url;
    this.editEvents = [...webhook.events];
    this.formError.set('');
    this.showForm.set(true);
  }

  toggleEvent(evt: WebhookEvent): void {
    if (this.formEvents.includes(evt)) {
      this.formEvents = this.formEvents.filter((event) => event !== evt);
    } else {
      this.formEvents = [...this.formEvents, evt];
    }
  }

  toggleEditEvent(evt: WebhookEvent): void {
    if (this.editEvents.includes(evt)) {
      this.editEvents = this.editEvents.filter((event) => event !== evt);
    } else {
      this.editEvents = [...this.editEvents, evt];
    }
  }

  create(): void {
    if (!this.formUrl.trim()) {
      this.formError.set('Endpoint URL is required.');
      return;
    }
    if (this.formEvents.length === 0) {
      this.formError.set('Select at least one event.');
      return;
    }
    this.saving.set(true);
    this.formError.set('');
    const body: WebhookCreate = { url: this.formUrl.trim(), events: [...this.formEvents] };
    this.svc.create(body).subscribe({
      next: (res) => {
        this.saving.set(false);
        this.createdSecret.set(res.secret);
        this.loadList();
      },
      error: (err) => {
        this.formError.set(err?.error?.detail ?? 'Failed to create webhook.');
        this.saving.set(false);
      },
    });
  }

  saveEdit(): void {
    const webhook = this.editingWebhook();
    if (!webhook) return;
    if (!this.editUrl.trim()) {
      this.formError.set('Endpoint URL is required.');
      return;
    }
    if (this.editEvents.length === 0) {
      this.formError.set('Select at least one event.');
      return;
    }
    this.saving.set(true);
    this.formError.set('');
    const body: WebhookUpdate = {
      url: this.editUrl.trim(),
      events: [...this.editEvents],
    };
    this.svc.update(webhook.id, body).subscribe({
      next: (updated) => {
        this.items.update((list) => list.map((item) => (item.id === webhook.id ? updated : item)));
        this.saving.set(false);
        this.cancelForm();
      },
      error: (err) => {
        this.formError.set(err?.error?.detail ?? 'Failed to save changes.');
        this.saving.set(false);
      },
    });
  }

  toggleActive(webhook: Webhook): void {
    this.svc.update(webhook.id, { active: !webhook.active }).subscribe({
      next: (updated) => this.items.update((list) => list.map((item) => (item.id === webhook.id ? updated : item))),
    });
  }

  remove(id: string): void {
    this.svc.delete(id).subscribe({
      next: () => this.items.update((list) => list.filter((webhook) => webhook.id !== id)),
    });
  }

  retryDelivery(webhookId: string, deliveryId: string): void {
    if (!this.canRetryDeliveries()) {
      return;
    }
    this.retryingDeliveryId.set(deliveryId);
    this.svc.retryDelivery(webhookId, deliveryId).subscribe({
      next: (delivery) => {
        this.deliveriesMap.update((state) => ({
          ...state,
          [webhookId]: [delivery, ...this.deliveriesFor(webhookId)],
        }));
        this.retryingDeliveryId.set(null);
      },
      error: (err) => {
        const message = err?.error?.detail ?? 'Retry failed.';
        this.deliveriesErrorMap.update((state) => ({ ...state, [webhookId]: message }));
        this.retryingDeliveryId.set(null);
      },
    });
  }

  cancelForm(): void {
    this.showForm.set(false);
    this.editingWebhook.set(null);
    this.formUrl = '';
    this.formEvents = [...AVAILABLE_EVENTS];
    this.editUrl = '';
    this.editEvents = [...AVAILABLE_EVENTS];
    this.formError.set('');
    this.createdSecret.set('');
  }

  deliveryStatusVariant(status: WebhookDelivery['status']): 'success' | 'warning' | 'danger' | 'neutral' {
    if (status === 'success') return 'success';
    if (status === 'failed') return 'danger';
    if (status === 'pending') return 'warning';
    return 'neutral';
  }

  private loadRole(): void {
    this.orgSvc.getMe().subscribe({
      next: (org) => this.orgRole.set(org.role),
    });
  }

  private loadDeliveries(webhookId: string): void {
    this.deliveriesLoadingMap.update((state) => ({ ...state, [webhookId]: true }));
    this.deliveriesErrorMap.update((state) => {
      const next = { ...state };
      delete next[webhookId];
      return next;
    });

    this.svc.listDeliveries(webhookId).subscribe({
      next: (deliveries) => {
        this.deliveriesMap.update((state) => ({ ...state, [webhookId]: deliveries }));
        this.deliveriesLoadingMap.update((state) => ({ ...state, [webhookId]: false }));
      },
      error: () => {
        this.deliveriesLoadingMap.update((state) => ({ ...state, [webhookId]: false }));
        this.deliveriesErrorMap.update((state) => ({
          ...state,
          [webhookId]: 'Unable to load delivery history for this webhook.',
        }));
      },
    });
  }
}
