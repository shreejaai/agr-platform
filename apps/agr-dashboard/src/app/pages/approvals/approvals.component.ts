import {
  Component,
  inject,
  OnInit,
  OnDestroy,
  ChangeDetectionStrategy,
  signal,
  computed,
} from '@angular/core';
import { JsonPipe, NgClass, DatePipe, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApprovalService } from '../../services/approval.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { Approval } from '../../core/models/approval.model';

type StatusFilter = '' | 'pending' | 'approved' | 'rejected';

const STATUS_TABS: { label: string; value: StatusFilter }[] = [
  { label: 'All', value: '' },
  { label: 'Pending', value: 'pending' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
];

/** Returns a human-readable SLA countdown string or null if not applicable. */
function slaCountdown(expiresAt: string): { label: string; urgent: boolean } | null {
  const exp = new Date(expiresAt).getTime();
  const now = Date.now();
  const diffMs = exp - now;
  if (diffMs <= 0) return { label: 'Expired', urgent: true };
  const diffSec = Math.floor(diffMs / 1000);
  const h = Math.floor(diffSec / 3600);
  const m = Math.floor((diffSec % 3600) / 60);
  const s = diffSec % 60;
  const urgent = diffMs < 30 * 60 * 1000; // < 30 min
  if (h > 0) return { label: `${h}h ${m}m`, urgent };
  if (m > 0) return { label: `${m}m ${s}s`, urgent };
  return { label: `${s}s`, urgent: true };
}

@Component({
  selector: 'agr-approvals',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, JsonPipe, NgClass, NgIf, DatePipe, BadgeComponent, RelativeTimePipe],
  template: `
    <div class="space-y-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">Approvals</h1>
        <p class="text-sm text-slate-400 mt-1">Review and decide on pending agent tool calls.</p>
      </div>

      <!-- Status filter tabs -->
      <div class="flex items-center gap-1 border-b border-slate-700 pb-0">
        @for (tab of statusTabs; track tab.value) {
          <button
            (click)="selectTab(tab.value)"
            [ngClass]="statusFilter === tab.value
              ? 'border-b-2 border-indigo-500 text-indigo-400 bg-indigo-500/5'
              : 'text-slate-500 hover:text-slate-200 border-b-2 border-transparent hover:border-slate-600'"
            class="px-4 py-2 text-sm font-medium transition-all rounded-t-md"
          >
            {{ tab.label }}
            @if (tab.value === 'pending' && pendingCount() > 0) {
              <span class="ml-1.5 inline-flex items-center justify-center w-4 h-4 rounded-full bg-amber-500/20 text-amber-400 text-xs font-bold">
                {{ pendingCount() }}
              </span>
            }
          </button>
        }
      </div>

      @if (loading()) {
        <div class="py-16 text-center text-slate-500 text-sm">Loading…</div>
      } @else if (items().length === 0) {
        <div class="card py-16 text-center">
          <p class="text-slate-400">No approvals found.</p>
          <p class="text-slate-500 text-xs mt-1">Pending tool calls from AI agents will appear here.</p>
        </div>
      } @else {
        <div class="space-y-3">
          @for (item of items(); track item.id) {
            <div
              class="card transition-colors"
              [ngClass]="{
                'border-amber-500/30 hover:border-amber-500/50': item.status === 'pending',
                'border-slate-700/50 hover:border-slate-600': item.status !== 'pending'
              }"
            >
              <div class="flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                  <!-- Status + time row -->
                  <div class="flex items-center gap-2 mb-1.5 flex-wrap">
                    <agr-badge [variant]="statusVariant(item.status)">{{ item.status }}</agr-badge>
                    <span class="text-xs text-slate-500">{{ item.created_at | relativeTime }}</span>

                    <!-- SLA countdown for pending items -->
                    @if (item.status === 'pending') {
                      <ng-container *ngIf="slaFor(item.id) as sla">
                        <span
                          [ngClass]="sla.urgent
                            ? 'bg-red-500/15 text-red-400 border border-red-500/30'
                            : 'bg-slate-700/60 text-slate-400 border border-slate-600'"
                          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono"
                        >
                          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          {{ sla.label }}
                        </span>
                      </ng-container>
                    }
                  </div>

                  <p class="text-sm font-medium text-slate-200">
                    Action: <span class="font-mono text-indigo-300">{{ item.action }}</span>
                    on <span class="font-mono text-slate-300">{{ item.resource }}</span>
                  </p>
                  <p class="text-xs text-slate-400 mt-0.5 truncate">
                    Agent: <span class="font-mono">{{ item.agent_id }}</span>
                  </p>

                  @if (item.approver_email) {
                    <p class="text-xs text-slate-500 mt-0.5">
                      Approver: {{ item.approver_email }}
                    </p>
                  }

                  @if (item.decision_at) {
                    <p class="text-xs text-slate-500 mt-0.5">
                      Decided: {{ item.decision_at | date:'medium' }}
                    </p>
                  }

                  @if (item.context && objectKeys(item.context).length > 0) {
                    <details class="mt-2">
                      <summary class="text-xs text-slate-500 cursor-pointer hover:text-slate-300">
                        Context / tool input
                      </summary>
                      <pre class="mt-1 text-xs bg-slate-900 rounded p-2 overflow-x-auto text-slate-300">{{
                        item.context | json
                      }}</pre>
                    </details>
                  }

                  <!-- Reason form shown while deciding -->
                  @if (item.status === 'pending' && decidingId() === item.id) {
                    <div class="mt-2 space-y-1.5">
                      <input
                        [(ngModel)]="decisionReason"
                        type="text"
                        placeholder="Reason (optional)"
                        class="input text-xs w-full"
                      />
                      <div class="flex gap-2">
                        <button
                          (click)="confirmDecide(item.id, 'approve')"
                          class="px-3 py-1.5 text-xs font-medium rounded-lg
                                 bg-green-500/15 text-green-400 border border-green-500/30
                                 hover:bg-green-500/25 transition-colors"
                        >Confirm Approve</button>
                        <button
                          (click)="confirmDecide(item.id, 'reject')"
                          class="px-3 py-1.5 text-xs font-medium rounded-lg
                                 bg-red-500/15 text-red-400 border border-red-500/30
                                 hover:bg-red-500/25 transition-colors"
                        >Confirm Reject</button>
                        <button
                          (click)="decidingId.set(null); decisionReason = ''"
                          class="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                        >Cancel</button>
                      </div>
                    </div>
                  }

                  <!-- Escalate form -->
                  @if (item.status === 'pending' && !item.approver_email && escalatingId() === item.id) {
                    <div class="mt-2 flex items-center gap-2">
                      <input
                        [(ngModel)]="escalateEmail"
                        type="email"
                        placeholder="approver@example.com"
                        class="input text-xs flex-1"
                      />
                      <button
                        (click)="escalate(item.id)"
                        class="px-2 py-1 text-xs rounded bg-slate-700 text-slate-200 hover:bg-slate-600"
                      >Send</button>
                      <button
                        (click)="escalatingId.set(null)"
                        class="text-xs text-slate-500 hover:text-slate-300"
                      >Cancel</button>
                    </div>
                  }
                </div>

                <!-- Action buttons -->
                @if (item.status === 'pending' && decidingId() !== item.id) {
                  <div class="flex flex-col gap-1.5 shrink-0">
                    <button
                      (click)="startDecide(item.id, 'approve')"
                      class="px-3 py-1.5 text-xs font-medium rounded-lg
                             bg-green-500/15 text-green-400 border border-green-500/30
                             hover:bg-green-500/25 transition-colors"
                    >Approve</button>
                    <button
                      (click)="startDecide(item.id, 'reject')"
                      class="px-3 py-1.5 text-xs font-medium rounded-lg
                             bg-red-500/15 text-red-400 border border-red-500/30
                             hover:bg-red-500/25 transition-colors"
                    >Reject</button>
                    @if (!item.approver_email) {
                      <button
                        (click)="escalatingId.set(item.id); escalateEmail = ''"
                        class="px-3 py-1.5 text-xs font-medium rounded-lg
                               bg-slate-700 text-slate-300 border border-slate-600
                               hover:bg-slate-600 transition-colors"
                      >Escalate</button>
                    }
                  </div>
                }
              </div>
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class ApprovalsComponent implements OnInit, OnDestroy {
  private svc = inject(ApprovalService);

  readonly statusTabs = STATUS_TABS;
  statusFilter: StatusFilter = 'pending';
  escalateEmail = '';
  decisionReason = '';

  // id of item being decided (shows inline reason form)
  readonly decidingId = signal<string | null>(null);
  // pending action staged for the confirm step
  private pendingAction: 'approve' | 'reject' | null = null;

  readonly loading = signal(true);
  readonly escalatingId = signal<string | null>(null);
  readonly items = signal<Approval[]>([]);
  readonly objectKeys = Object.keys;

  readonly pendingCount = computed(() => this.items().filter((a) => a.status === 'pending').length);

  // SLA countdowns refreshed every second
  private slaMap = signal<Map<string, { label: string; urgent: boolean }>>(new Map());
  private slaInterval: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    this.load();
    this.slaInterval = setInterval(() => this.refreshSla(), 1000);
  }

  ngOnDestroy(): void {
    if (this.slaInterval) clearInterval(this.slaInterval);
  }

  selectTab(value: StatusFilter): void {
    this.statusFilter = value;
    this.load();
  }

  load(): void {
    this.loading.set(true);
    const params = this.statusFilter ? { status: this.statusFilter, limit: 50 } : { limit: 50 };
    this.svc.list(params).subscribe({
      next: (res) => {
        this.items.set(res);
        this.loading.set(false);
        this.refreshSla();
      },
      error: () => this.loading.set(false),
    });
  }

  slaFor(id: string): { label: string; urgent: boolean } | null {
    return this.slaMap().get(id) ?? null;
  }

  private refreshSla(): void {
    const pending = this.items().filter((a) => a.status === 'pending');
    const map = new Map<string, { label: string; urgent: boolean }>();
    for (const a of pending) {
      const result = slaCountdown(a.expires_at);
      if (result) map.set(a.id, result);
    }
    this.slaMap.set(map);
  }

  startDecide(id: string, action: 'approve' | 'reject'): void {
    this.pendingAction = action;
    this.decisionReason = '';
    this.decidingId.set(id);
  }

  confirmDecide(id: string, action: 'approve' | 'reject'): void {
    const call = action === 'approve'
      ? this.svc.approve(id, this.decisionReason)
      : this.svc.reject(id, this.decisionReason);

    call.subscribe({
      next: (updated) => {
        this.items.update((list) => list.map((a) => (a.id === id ? updated : a)));
        this.decidingId.set(null);
        this.decisionReason = '';
        this.pendingAction = null;
        this.refreshSla();
      },
      error: () => {
        this.decidingId.set(null);
        this.pendingAction = null;
      },
    });
  }

  escalate(id: string): void {
    if (!this.escalateEmail.trim()) return;
    this.svc.escalate(id, this.escalateEmail.trim()).subscribe({
      next: (updated) => {
        this.items.update((list) => list.map((a) => (a.id === id ? updated : a)));
        this.escalatingId.set(null);
      },
    });
  }

  statusVariant(status: string): 'warning' | 'success' | 'danger' | 'neutral' {
    const map: Record<string, 'warning' | 'success' | 'danger' | 'neutral'> = {
      pending: 'warning',
      approved: 'success',
      rejected: 'danger',
    };
    return map[status] ?? 'neutral';
  }
}
