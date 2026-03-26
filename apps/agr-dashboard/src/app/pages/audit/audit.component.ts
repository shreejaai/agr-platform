import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuditService, AuditVerifyResult } from '../../services/audit.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { AuditEvent } from '../../core/models/audit-event.model';

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
                <tr class="table-row">
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
                  </td>
                  <td class="table-cell text-right text-slate-400 whitespace-nowrap">
                    {{ ev.recorded_at | relativeTime }}
                  </td>
                </tr>
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
    this.load();
  }

  prevPage(): void {
    this.offset.update((o) => Math.max(0, o - this.pageSize));
    this.load();
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

  decisionVariant(decision: string): 'success' | 'danger' | 'warning' | 'neutral' {
    if (decision === 'ALLOW') return 'success';
    if (decision === 'DENY') return 'danger';
    if (decision === 'APPROVAL_REQUIRED') return 'warning';
    return 'neutral';
  }
}
