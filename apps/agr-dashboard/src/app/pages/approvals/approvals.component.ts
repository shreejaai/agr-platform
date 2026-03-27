import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DatePipe, JsonPipe, NgClass, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApprovalService } from '../../services/approval.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { Approval, ApprovalStep } from '../../core/models/approval.model';

type StatusFilter = '' | 'pending' | 'approved' | 'rejected';
type HistoryTone = 'neutral' | 'warning' | 'success' | 'danger';

interface ApprovalHistoryItem {
  label: string;
  timestamp: string;
  detail: string;
  tone: HistoryTone;
}

const STATUS_TABS: { label: string; value: StatusFilter }[] = [
  { label: 'All', value: '' },
  { label: 'Pending', value: 'pending' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
];

function slaCountdown(expiresAt: string): { label: string; urgent: boolean } | null {
  const exp = new Date(expiresAt).getTime();
  const now = Date.now();
  const diffMs = exp - now;
  if (diffMs <= 0) return { label: 'Expired', urgent: true };
  const diffSec = Math.floor(diffMs / 1000);
  const h = Math.floor(diffSec / 3600);
  const m = Math.floor((diffSec % 3600) / 60);
  const s = diffSec % 60;
  const urgent = diffMs < 30 * 60 * 1000;
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
        <p class="text-sm text-slate-400 mt-1">
          Review approval workflows, inspect approver steps, and decide on pending agent actions.
        </p>
      </div>

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
        <div class="py-16 text-center text-slate-500 text-sm">Loading...</div>
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
                  <div class="flex items-center gap-2 mb-1.5 flex-wrap">
                    <agr-badge [variant]="statusVariant(item.status)">{{ item.status }}</agr-badge>
                    <span class="text-xs text-slate-500">{{ item.created_at | relativeTime }}</span>
                    <span
                      class="inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide"
                      [ngClass]="workflowModeClass(item.workflow_mode)"
                    >
                      {{ item.workflow_mode === 'temporal' ? 'Temporal' : 'DB only' }}
                    </span>
                    <span
                      class="inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide"
                      [ngClass]="workflowStatusClass(item.workflow_status)"
                    >
                      {{ item.workflow_status }}
                    </span>

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

                  <div class="mt-2 flex flex-wrap gap-2 text-[11px]">
                    <span class="inline-flex items-center rounded-md border border-slate-700 px-2 py-1 text-slate-300">
                      Quorum: <span class="ml-1 font-mono">{{ item.quorum_type }}</span>
                    </span>
                    @if (item.sla_hours !== null) {
                      <span class="inline-flex items-center rounded-md border border-slate-700 px-2 py-1 text-slate-300">
                        SLA: <span class="ml-1 font-mono">{{ item.sla_hours }}h</span>
                      </span>
                    }
                    @if (item.approver_email) {
                      <span class="inline-flex items-center rounded-md border border-slate-700 px-2 py-1 text-slate-300">
                        Approver: <span class="ml-1 font-mono">{{ item.approver_email }}</span>
                      </span>
                    }
                    @if (item.escalation_email) {
                      <span class="inline-flex items-center rounded-md border border-slate-700 px-2 py-1 text-slate-300">
                        Escalates to: <span class="ml-1 font-mono">{{ item.escalation_email }}</span>
                      </span>
                    }
                  </div>

                  @if (item.decision_at) {
                    <p class="text-xs text-slate-500 mt-2">
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

                <div class="flex flex-col gap-1.5 shrink-0">
                  @if (item.status === 'pending' && decidingId() !== item.id) {
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
                  }

                  <button
                    (click)="toggleWorkflow(item.id)"
                    class="px-3 py-1.5 text-xs font-medium rounded-lg
                           bg-slate-800 text-slate-300 border border-slate-700
                           hover:bg-slate-700 transition-colors"
                  >
                    {{ expandedId() === item.id ? 'Hide workflow' : 'View workflow' }}
                  </button>
                </div>
              </div>

              @if (expandedId() === item.id) {
                <div class="mt-4 border-t border-slate-800 pt-4 grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
                  <div class="space-y-4">
                    <div class="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                      <h3 class="text-sm font-semibold text-slate-100">Workflow details</h3>
                      <dl class="mt-3 space-y-2 text-xs">
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Workflow mode</dt>
                          <dd class="font-mono text-slate-300">
                            {{ item.workflow_mode }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Workflow status</dt>
                          <dd class="font-mono text-slate-300">{{ item.workflow_status }}</dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Temporal run ID</dt>
                          <dd class="font-mono text-slate-300 break-all text-right">
                            {{ item.temporal_run_id ?? 'Not running in Temporal' }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Fallback mode</dt>
                          <dd class="font-mono text-slate-300 break-all text-right">
                            {{ item.workflow_fallback_mode }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Last transition</dt>
                          <dd class="font-mono text-slate-300 text-right">
                            {{ item.workflow_last_transition_at ? (item.workflow_last_transition_at | date:'medium') : 'Not recorded' }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Quorum</dt>
                          <dd class="font-mono text-slate-300">{{ item.quorum_type }}</dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Configured SLA</dt>
                          <dd class="font-mono text-slate-300">
                            {{ item.sla_hours !== null ? item.sla_hours + 'h' : 'Not configured' }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Expires at</dt>
                          <dd class="font-mono text-slate-300 text-right">
                            {{ item.expires_at | date:'medium' }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Current approver</dt>
                          <dd class="font-mono text-slate-300 break-all text-right">
                            {{ item.approver_email ?? 'Unassigned' }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-4">
                          <dt class="text-slate-500">Escalation target</dt>
                          <dd class="font-mono text-slate-300 break-all text-right">
                            {{ item.escalation_email ?? 'Not configured' }}
                          </dd>
                        </div>
                      </dl>
                      @if (item.workflow_last_error) {
                        <div class="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                          {{ item.workflow_last_error }}
                        </div>
                      }
                    </div>

                    <div class="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                      <div class="flex items-center justify-between gap-4">
                        <h3 class="text-sm font-semibold text-slate-100">Approver steps</h3>
                        @if (stepsLoadingFor(item.id)) {
                          <span class="text-xs text-slate-500">Loading steps...</span>
                        }
                      </div>

                      @if (stepsErrorFor(item.id)) {
                        <div class="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                          {{ stepsErrorFor(item.id) }}
                        </div>
                      } @else if (stepsFor(item.id).length === 0) {
                        <p class="mt-3 text-xs text-slate-500">No approval steps recorded for this workflow.</p>
                      } @else {
                        <div class="mt-3 space-y-2">
                          @for (step of stepsFor(item.id); track step.id) {
                            <div class="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-3">
                              <div class="flex items-center justify-between gap-3">
                                <div>
                                  <p class="text-xs text-slate-400">Approver</p>
                                  <p class="text-sm font-mono text-slate-200">{{ step.approver_email }}</p>
                                </div>
                                <agr-badge [variant]="statusVariant(step.status)">{{ step.status }}</agr-badge>
                              </div>
                              <div class="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
                                <span>Created: {{ step.created_at | date:'medium' }}</span>
                                @if (step.decided_at) {
                                  <span>Decided: {{ step.decided_at | date:'medium' }}</span>
                                }
                              </div>
                            </div>
                          }
                        </div>
                      }
                    </div>
                  </div>

                  <div class="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                    <h3 class="text-sm font-semibold text-slate-100">Status history</h3>

                    @if (historyFor(item).length === 0) {
                      <p class="mt-3 text-xs text-slate-500">No workflow history available yet.</p>
                    } @else {
                      <div class="mt-4 space-y-3">
                        @for (historyItem of historyFor(item); track historyItem.label + historyItem.timestamp + historyItem.detail) {
                          <div class="flex gap-3">
                            <div class="mt-1 h-2.5 w-2.5 rounded-full" [ngClass]="historyToneClass(historyItem.tone)"></div>
                            <div class="min-w-0">
                              <p class="text-sm text-slate-200">{{ historyItem.label }}</p>
                              <p class="text-xs text-slate-500 mt-0.5">{{ historyItem.timestamp | date:'medium' }}</p>
                              <p class="text-xs text-slate-400 mt-1 break-words">{{ historyItem.detail }}</p>
                            </div>
                          </div>
                        }
                      </div>
                    }
                  </div>
                </div>
              }
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class ApprovalsComponent implements OnInit, OnDestroy {
  private readonly svc = inject(ApprovalService);

  readonly statusTabs = STATUS_TABS;
  statusFilter: StatusFilter = 'pending';
  escalateEmail = '';
  decisionReason = '';

  readonly decidingId = signal<string | null>(null);
  readonly expandedId = signal<string | null>(null);
  readonly loading = signal(true);
  readonly escalatingId = signal<string | null>(null);
  readonly items = signal<Approval[]>([]);
  readonly stepMap = signal<Record<string, ApprovalStep[]>>({});
  readonly stepLoadingMap = signal<Record<string, boolean>>({});
  readonly stepErrorMap = signal<Record<string, string>>({});
  readonly objectKeys = Object.keys;

  readonly pendingCount = computed(() => this.items().filter((approval) => approval.status === 'pending').length);

  private readonly slaMap = signal<Map<string, { label: string; urgent: boolean }>>(new Map());
  private slaInterval: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    this.load();
    this.slaInterval = setInterval(() => this.refreshSla(), 1000);
  }

  ngOnDestroy(): void {
    if (this.slaInterval) {
      clearInterval(this.slaInterval);
    }
  }

  selectTab(value: StatusFilter): void {
    this.statusFilter = value;
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.expandedId.set(null);
    const params = this.statusFilter ? { status: this.statusFilter, limit: 50 } : { limit: 50 };
    this.svc.list(params).subscribe({
      next: (approvals) => {
        this.items.set(approvals);
        this.loading.set(false);
        this.refreshSla();
      },
      error: () => this.loading.set(false),
    });
  }

  toggleWorkflow(id: string): void {
    const isExpanded = this.expandedId() === id;
    this.expandedId.set(isExpanded ? null : id);
    if (!isExpanded && this.stepsFor(id).length === 0 && !this.stepsLoadingFor(id)) {
      this.loadSteps(id);
    }
  }

  slaFor(id: string): { label: string; urgent: boolean } | null {
    return this.slaMap().get(id) ?? null;
  }

  stepsFor(id: string): ApprovalStep[] {
    return this.stepMap()[id] ?? [];
  }

  stepsLoadingFor(id: string): boolean {
    return this.stepLoadingMap()[id] ?? false;
  }

  stepsErrorFor(id: string): string | null {
    return this.stepErrorMap()[id] ?? null;
  }

  historyFor(item: Approval): ApprovalHistoryItem[] {
    const history: ApprovalHistoryItem[] = [
      {
        label: 'Approval requested',
        timestamp: item.created_at,
        detail: `${item.agent_id} requested ${item.action} on ${item.resource}.`,
        tone: 'neutral',
      },
    ];

    for (const step of this.stepsFor(item.id)) {
      history.push({
        label: 'Approver step added',
        timestamp: step.created_at,
        detail: step.approver_email,
        tone: 'warning',
      });

      if (step.decided_at) {
        history.push({
          label: `Step ${step.status}`,
          timestamp: step.decided_at,
          detail: step.approver_email,
          tone: step.status === 'approved' ? 'success' : 'danger',
        });
      }
    }

    if (item.decision_at) {
      history.push({
        label: item.status === 'approved' ? 'Approval completed' : 'Approval rejected',
        timestamp: item.decision_at,
        detail: item.approver_email ?? item.workflow_mode,
        tone: item.status === 'approved' ? 'success' : 'danger',
      });
    }

    if (item.workflow_escalated_at) {
      history.push({
        label: 'Workflow escalated',
        timestamp: item.workflow_escalated_at,
        detail: item.approver_email ?? item.escalation_email ?? item.workflow_mode,
        tone: 'warning',
      });
    }

    if (item.workflow_status === 'failed' && item.workflow_last_transition_at) {
      history.push({
        label: 'Workflow failed',
        timestamp: item.workflow_last_transition_at,
        detail: item.workflow_last_error ?? item.workflow_fallback_mode,
        tone: 'danger',
      });
    }

    return history.sort(
      (left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime(),
    );
  }

  startDecide(id: string, action: 'approve' | 'reject'): void {
    this.decisionReason = '';
    this.decidingId.set(id);
  }

  confirmDecide(id: string, action: 'approve' | 'reject'): void {
    const request =
      action === 'approve' ? this.svc.approve(id, this.decisionReason) : this.svc.reject(id, this.decisionReason);

    request.subscribe({
      next: (updated) => {
        this.items.update((approvals) => approvals.map((approval) => (approval.id === id ? updated : approval)));
        this.decidingId.set(null);
        this.decisionReason = '';
        this.refreshSla();
      },
      error: () => {
        this.decidingId.set(null);
      },
    });
  }

  escalate(id: string): void {
    if (!this.escalateEmail.trim()) {
      return;
    }
    this.svc.escalate(id, this.escalateEmail.trim()).subscribe({
      next: (updated) => {
        this.items.update((approvals) => approvals.map((approval) => (approval.id === id ? updated : approval)));
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

  workflowModeClass(mode: Approval['workflow_mode']): string {
    return mode === 'temporal'
      ? 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300'
      : 'border-slate-600 bg-slate-700/50 text-slate-300';
  }

  workflowStatusClass(status: Approval['workflow_status']): string {
    switch (status) {
      case 'completed':
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
      case 'failed':
        return 'border-red-500/30 bg-red-500/10 text-red-300';
      case 'escalated':
        return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
      default:
        return 'border-slate-600 bg-slate-700/50 text-slate-300';
    }
  }

  historyToneClass(tone: HistoryTone): string {
    switch (tone) {
      case 'warning':
        return 'bg-amber-400';
      case 'success':
        return 'bg-emerald-400';
      case 'danger':
        return 'bg-red-400';
      default:
        return 'bg-slate-500';
    }
  }

  private refreshSla(): void {
    const pending = this.items().filter((approval) => approval.status === 'pending');
    const nextMap = new Map<string, { label: string; urgent: boolean }>();
    for (const approval of pending) {
      const nextValue = slaCountdown(approval.expires_at);
      if (nextValue) {
        nextMap.set(approval.id, nextValue);
      }
    }
    this.slaMap.set(nextMap);
  }

  private loadSteps(id: string): void {
    this.stepLoadingMap.update((state) => ({ ...state, [id]: true }));
    this.stepErrorMap.update((state) => {
      const next = { ...state };
      delete next[id];
      return next;
    });

    this.svc.listSteps(id).subscribe({
      next: (steps) => {
        this.stepMap.update((state) => ({ ...state, [id]: steps }));
        this.stepLoadingMap.update((state) => ({ ...state, [id]: false }));
      },
      error: () => {
        this.stepLoadingMap.update((state) => ({ ...state, [id]: false }));
        this.stepErrorMap.update((state) => ({
          ...state,
          [id]: 'Unable to load approval steps for this workflow.',
        }));
      },
    });
  }
}
