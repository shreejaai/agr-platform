import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuditService, AuditVerifyResult } from '../../services/audit.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { AuditEvent, AuditPayload } from '../../core/models/audit-event.model';

const EVENT_TYPES = [
  'TOOL_ALLOW', 'TOOL_DENY', 'APPROVAL_REQUESTED', 'APPROVAL_APPROVED', 'APPROVAL_REJECTED',
];

const DECISIONS = ['ALLOW', 'DENY', 'APPROVAL_REQUIRED'];

@Component({
  selector: 'agr-audit',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, BadgeComponent, RelativeTimePipe],
  template: `
    <div class="space-y-4">
      <div class="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 class="text-2xl font-bold text-slate-100">Audit Log</h1>
          <p class="text-sm text-slate-400 mt-1">Immutable, hash-chained record of all governance events.</p>
        </div>

        <!-- Hash chain validity badge -->
        <div class="flex items-center gap-2">
          @if (verifying()) {
            <span class="text-xs text-slate-500 animate-pulse">Verifying chain…</span>
          } @else if (chainResult()) {
            @if (chainResult()!.valid) {
              <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                           bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                Chain valid ({{ chainResult()!.total }} events)
              </span>
            } @else {
              <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                           bg-red-500/15 text-red-400 border border-red-500/30">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
                Chain broken at #{{ chainResult()!.first_invalid_sequence }}
              </span>
            }
          }

          <button
            (click)="verifyChain()"
            [disabled]="verifying()"
            class="text-xs text-slate-500 hover:text-slate-200 underline transition-colors disabled:opacity-50"
          >Verify chain</button>
        </div>
      </div>

      <!-- Filters -->
      <div class="card">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-3">
          <div>
            <label for="audit-event-type" class="block text-xs text-slate-400 mb-1">Event type</label>
            <select id="audit-event-type" [(ngModel)]="filterType" (ngModelChange)="resetAndLoad()" class="input w-full text-sm">
              <option value="">All types</option>
              @for (t of eventTypes; track t) {
                <option [value]="t">{{ t }}</option>
              }
            </select>
          </div>
          <div>
            <label for="audit-decision" class="block text-xs text-slate-400 mb-1">Decision</label>
            <select id="audit-decision" [(ngModel)]="filterDecision" (ngModelChange)="resetAndLoad()" class="input w-full text-sm">
              <option value="">All decisions</option>
              @for (d of decisions; track d) {
                <option [value]="d">{{ d }}</option>
              }
            </select>
          </div>
          <div>
            <label for="audit-agent-id" class="block text-xs text-slate-400 mb-1">Agent ID</label>
            <input
              id="audit-agent-id"
              [(ngModel)]="filterAgent"
              (blur)="resetAndLoad()"
              (keydown.enter)="resetAndLoad()"
              class="input w-full text-sm font-mono"
              placeholder="agent-id…"
            />
          </div>
          <div>
            <label for="audit-action" class="block text-xs text-slate-400 mb-1">Action</label>
            <input
              id="audit-action"
              [(ngModel)]="filterAction"
              (blur)="resetAndLoad()"
              (keydown.enter)="resetAndLoad()"
              class="input w-full text-sm font-mono"
              placeholder="web_search…"
            />
          </div>
          <div>
            <label for="audit-start-date" class="block text-xs text-slate-400 mb-1">From date</label>
            <input
              id="audit-start-date"
              [(ngModel)]="filterStartDate"
              (change)="resetAndLoad()"
              class="input w-full text-sm"
              type="date"
            />
          </div>
          <div>
            <label for="audit-end-date" class="block text-xs text-slate-400 mb-1">To date</label>
            <input
              id="audit-end-date"
              [(ngModel)]="filterEndDate"
              (change)="resetAndLoad()"
              class="input w-full text-sm"
              type="date"
            />
          </div>
        </div>

        <!-- Filter actions row -->
        <div class="flex items-center justify-between flex-wrap gap-2">
          <button
            (click)="clearFilters()"
            class="text-xs text-slate-500 hover:text-slate-200 underline transition-colors"
          >Clear filters</button>

          <button
            (click)="exportAudit()"
            [disabled]="exporting()"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                   bg-indigo-500/15 text-indigo-400 border border-indigo-500/30
                   hover:bg-indigo-500/25 disabled:opacity-50 transition-colors"
          >
            @if (exporting()) {
              <span>Exporting…</span>
            } @else {
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export JSON
            }
          </button>
        </div>

        @if (exportError()) {
          <p class="text-xs text-red-400 mt-2">{{ exportError() }}</p>
        }
      </div>

      <!-- Table -->
      @if (loading()) {
        <div class="py-16 text-center text-slate-500 text-sm">Loading…</div>
      } @else if (items().length === 0) {
        <div class="card py-16 text-center">
          <p class="text-slate-400">No audit events found.</p>
          <p class="text-slate-500 text-xs mt-1">Try adjusting your filters.</p>
        </div>
      } @else {
        <div class="card overflow-hidden p-0">
          <table class="w-full text-sm">
            <thead>
              <tr>
                <th class="table-header w-6"></th>
                <th class="table-header">Event</th>
                <th class="table-header">Agent</th>
                <th class="table-header">Action</th>
                <th class="table-header">Resource</th>
                <th class="table-header">Decision</th>
                <th class="table-header text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              @for (ev of items(); track ev.id) {
                <!-- Main row — click to toggle detail -->
                <tr
                  class="table-row cursor-pointer select-none"
                  (click)="toggleDetail(ev.id)"
                >
                  <td class="table-cell text-slate-500 text-xs">
                    <svg
                      class="w-3 h-3 transition-transform"
                      [class.rotate-90]="expandedId() === ev.id"
                      fill="none" stroke="currentColor" viewBox="0 0 24 24"
                    >
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                    </svg>
                  </td>
                  <td class="table-cell">
                    <agr-badge [variant]="eventVariant(ev.event_type)">{{ ev.event_type }}</agr-badge>
                  </td>
                  <td class="table-cell font-mono text-xs text-slate-300 max-w-[120px] truncate">
                    {{ ev.agent_id }}
                  </td>
                  <td class="table-cell font-mono text-xs text-slate-300">{{ ev.action }}</td>
                  <td class="table-cell text-xs text-slate-400 max-w-[140px] truncate">{{ ev.resource }}</td>
                  <td class="table-cell">
                    @if (ev.decision) {
                      <agr-badge [variant]="decisionVariant(ev.decision)">{{ ev.decision }}</agr-badge>
                    }
                    @if (blockReason(ev); as reason) {
                      <p class="text-[11px] text-slate-500 mt-0.5 leading-tight">{{ reason }}</p>
                    }
                  </td>
                  <td class="table-cell text-right text-slate-400 whitespace-nowrap">
                    {{ ev.recorded_at | relativeTime }}
                  </td>
                </tr>

                <!-- Detail panel — shown when row is expanded -->
                @if (expandedId() === ev.id) {
                  <tr>
                    <td colspan="7" class="px-4 pb-4 bg-slate-900/60 border-b border-slate-800">
                      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-3">

                        <!-- Decision context -->
                        <div class="space-y-2">
                          <h4 class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Decision Context</h4>
                          <div class="space-y-1 text-xs">
                            @if (ev.payload?.eval_id) {
                              <div class="flex gap-2">
                                <span class="text-slate-500 w-32 flex-shrink-0">Eval ID</span>
                                <span class="font-mono text-slate-300 truncate">{{ ev.payload!.eval_id }}</span>
                              </div>
                            }
                            @if (ev.policy_id) {
                              <div class="flex gap-2">
                                <span class="text-slate-500 w-32 flex-shrink-0">Policy ID</span>
                                <span class="font-mono text-slate-300 truncate">{{ ev.policy_id }}</span>
                              </div>
                            }
                            @if (ev.approval_id) {
                              <div class="flex gap-2">
                                <span class="text-slate-500 w-32 flex-shrink-0">Approval ID</span>
                                <span class="font-mono text-slate-300 truncate">{{ ev.approval_id }}</span>
                              </div>
                            }
                            @if (ev.payload?.policy_source) {
                              <div class="flex gap-2">
                                <span class="text-slate-500 w-32 flex-shrink-0">Engine</span>
                                <span class="font-mono text-slate-300">{{ ev.payload!.policy_source }}</span>
                              </div>
                            }
                            @if (ev.payload?.no_policy_fallback) {
                              <div class="flex gap-2">
                                <span class="text-slate-500 w-32 flex-shrink-0">Fallback mode</span>
                                <span class="font-mono text-amber-400">
                                  no_policy_action={{ ev.payload!.no_policy_action ?? 'deny' }}
                                </span>
                              </div>
                            }
                            @if (ev.payload?.fallback_used) {
                              <div class="flex gap-2">
                                <span class="text-slate-500 w-32 flex-shrink-0">Fallback reason</span>
                                <span class="font-mono text-amber-400 text-wrap">{{ ev.payload!.fallback_reason }}</span>
                              </div>
                            }
                            @if (ev.payload?.cached) {
                              <div class="flex gap-2">
                                <span class="text-slate-500 w-32 flex-shrink-0">Cache</span>
                                <span class="text-slate-400">Served from Redis cache</span>
                              </div>
                            }
                          </div>
                        </div>

                        <!-- Risk scoring -->
                        @if (ev.payload?.risk_score !== null && ev.payload?.risk_score !== undefined) {
                          <div class="space-y-2">
                            <h4 class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Risk Scoring</h4>
                            <div class="space-y-1 text-xs">
                              <div class="flex gap-2">
                                <span class="text-slate-500 w-32 flex-shrink-0">Score</span>
                                <span [class]="riskScoreClass(ev.payload!.risk_score!)">
                                  {{ ev.payload!.risk_score }}/100 ({{ ev.payload!.risk_level }})
                                </span>
                              </div>
                              @if (ev.payload!.risk_factors) {
                                @for (kv of riskFactorEntries(ev.payload!.risk_factors!); track kv[0]) {
                                  <div class="flex gap-2">
                                    <span class="text-slate-500 w-32 flex-shrink-0">{{ kv[0] }}</span>
                                    <span class="text-slate-300">{{ kv[1] }}</span>
                                  </div>
                                }
                              }
                            </div>
                          </div>
                        }

                        <!-- Compliance -->
                        @if (ev.payload?.compliance_blocked) {
                          <div class="space-y-2 md:col-span-2">
                            <h4 class="text-xs font-semibold text-red-400 uppercase tracking-wider">Compliance Block</h4>
                            <p class="text-xs text-red-300">{{ ev.payload!.compliance_block_reason }}</p>
                          </div>
                        }

                        <!-- Sequence & hash -->
                        <div class="space-y-2 md:col-span-2">
                          <h4 class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Chain Info</h4>
                          <div class="space-y-1 text-xs font-mono text-slate-500">
                            <div>seq: {{ ev.sequence_num }}</div>
                            <div class="truncate">hash: {{ ev.entry_hash }}</div>
                          </div>
                        </div>

                        <!-- Raw payload toggle -->
                        <div class="md:col-span-2">
                          <button
                            (click)="toggleRaw(ev.id); $event.stopPropagation()"
                            class="text-xs text-slate-500 hover:text-slate-300 underline"
                          >
                            {{ showRawId() === ev.id ? 'Hide' : 'Show' }} raw payload
                          </button>
                          @if (showRawId() === ev.id) {
                            <pre class="mt-2 p-3 bg-slate-950 rounded text-xs text-slate-400 overflow-auto max-h-64 whitespace-pre-wrap">{{ payloadJson(ev) }}</pre>
                          }
                        </div>
                      </div>
                    </td>
                  </tr>
                }
              }
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <div class="flex items-center justify-between text-xs text-slate-500">
          <span>Showing {{ items().length }} events (page {{ currentPage() + 1 }})</span>
          <div class="flex gap-2">
            <button
              (click)="prevPage()"
              [disabled]="offset() === 0"
              class="px-2 py-1 rounded hover:bg-slate-800 disabled:opacity-40 transition-colors"
            >← Prev</button>
            <button
              (click)="nextPage()"
              [disabled]="items().length < pageSize"
              class="px-2 py-1 rounded hover:bg-slate-800 disabled:opacity-40 transition-colors"
            >Next →</button>
          </div>
        </div>
      }
    </div>
  `,
})
export class AuditComponent implements OnInit {
  private svc = inject(AuditService);

  readonly pageSize = 50;
  readonly eventTypes = EVENT_TYPES;
  readonly decisions = DECISIONS;

  filterType = '';
  filterAgent = '';
  filterAction = '';
  filterDecision = '';
  filterStartDate = '';
  filterEndDate = '';

  readonly loading = signal(true);
  readonly verifying = signal(false);
  readonly exporting = signal(false);
  readonly offset = signal(0);
  readonly items = signal<AuditEvent[]>([]);
  readonly chainResult = signal<AuditVerifyResult | null>(null);
  readonly exportError = signal('');
  /** ID of the currently expanded row; null = all collapsed. */
  readonly expandedId = signal<string | null>(null);
  /** ID of the row showing raw JSON payload. */
  readonly showRawId = signal<string | null>(null);

  readonly currentPage = () => Math.floor(this.offset() / this.pageSize);

  ngOnInit(): void {
    this.load();
    this.verifyChain();
  }

  clearFilters(): void {
    this.filterType = '';
    this.filterAgent = '';
    this.filterAction = '';
    this.filterDecision = '';
    this.filterStartDate = '';
    this.filterEndDate = '';
    this.resetAndLoad();
  }

  resetAndLoad(): void {
    this.offset.set(0);
    this.expandedId.set(null);
    this.showRawId.set(null);
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.svc.search({
      event_type: (this.filterType as AuditEvent['event_type']) || undefined,
      agent_id: this.filterAgent.trim() || undefined,
      action: this.filterAction.trim() || undefined,
      decision: this.filterDecision || undefined,
      start_date: this.filterStartDate || undefined,
      end_date: this.filterEndDate || undefined,
      limit: this.pageSize,
      offset: this.offset(),
    }).subscribe({
      next: (res) => {
        this.items.set(res);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  nextPage(): void {
    this.offset.update((o) => o + this.pageSize);
    this.expandedId.set(null);
    this.showRawId.set(null);
    this.load();
  }

  prevPage(): void {
    this.offset.update((o) => Math.max(0, o - this.pageSize));
    this.expandedId.set(null);
    this.showRawId.set(null);
    this.load();
  }

  toggleDetail(id: string): void {
    this.expandedId.update((cur) => (cur === id ? null : id));
    if (this.showRawId() !== id) {
      this.showRawId.set(null);
    }
  }

  toggleRaw(id: string): void {
    this.showRawId.update((cur) => (cur === id ? null : id));
  }

  payloadJson(ev: AuditEvent): string {
    try {
      return JSON.stringify(ev.payload, null, 2);
    } catch {
      return String(ev.payload);
    }
  }

  riskFactorEntries(factors: Record<string, number>): [string, number][] {
    return Object.entries(factors);
  }

  riskScoreClass(score: number): string {
    if (score >= 71) return 'text-red-400 font-semibold';
    if (score >= 31) return 'text-amber-400 font-semibold';
    return 'text-emerald-400 font-semibold';
  }

  verifyChain(): void {
    this.verifying.set(true);
    this.svc.verify().subscribe({
      next: (res) => {
        this.chainResult.set(res);
        this.verifying.set(false);
      },
      error: () => this.verifying.set(false),
    });
  }

  exportAudit(): void {
    this.exporting.set(true);
    this.exportError.set('');
    this.svc.export({
      event_type: this.filterType || undefined,
      agent_id: this.filterAgent.trim() || undefined,
      action: this.filterAction.trim() || undefined,
      decision: this.filterDecision || undefined,
      start_date: this.filterStartDate || undefined,
      end_date: this.filterEndDate || undefined,
      format: 'json',
    }).subscribe({
      next: (blob) => {
        const date = new Date().toISOString().split('T')[0];
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `agr_audit_${date}.json`;
        a.click();
        URL.revokeObjectURL(url);
        this.exporting.set(false);
      },
      error: (err) => {
        const msg = err?.error?.detail ?? err?.error?.message ?? 'Export failed.';
        this.exportError.set(msg);
        this.exporting.set(false);
      },
    });
  }

  eventVariant(type: string): 'success' | 'danger' | 'warning' | 'info' | 'neutral' {
    const map: Record<string, 'success' | 'danger' | 'warning' | 'info' | 'neutral'> = {
      TOOL_ALLOW: 'success',
      TOOL_DENY: 'danger',
      APPROVAL_REQUESTED: 'warning',
      APPROVAL_APPROVED: 'success',
      APPROVAL_REJECTED: 'danger',
    };
    return map[type] ?? 'neutral';
  }

  blockReason(ev: AuditEvent): string | null {
    const p = ev.payload;
    if (!p) return null;
    if (p.compliance_blocked) return 'Compliance block';
    if (p.no_policy_fallback) return `No policy: ${p.no_policy_action ?? 'deny'}`;
    if (p.risk_score != null && ev.decision !== 'ALLOW') {
      return `Risk score: ${p.risk_score}`;
    }
    return null;
  }

  decisionVariant(decision: string): 'success' | 'danger' | 'warning' | 'neutral' {
    if (decision === 'ALLOW') return 'success';
    if (decision === 'DENY') return 'danger';
    if (decision === 'APPROVAL_REQUIRED') return 'warning';
    return 'neutral';
  }
}
