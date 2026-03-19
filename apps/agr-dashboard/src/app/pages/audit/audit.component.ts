import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuditService } from '../../services/audit.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { AuditEvent } from '../../models/audit-event.model';

const EVENT_TYPES = [
  'TOOL_ALLOW', 'TOOL_DENY', 'APPROVAL_REQUESTED', 'APPROVAL_APPROVED', 'APPROVAL_REJECTED',
];

@Component({
  selector: 'agr-audit',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, BadgeComponent, RelativeTimePipe],
  template: `
    <div class="space-y-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">Audit Log</h1>
        <p class="text-sm text-slate-400 mt-1">Immutable, hash-chained record of all governance events.</p>
      </div>

      <!-- Filters -->
      <div class="card">
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label class="block text-xs text-slate-400 mb-1">Event type</label>
            <select [(ngModel)]="filterType" (ngModelChange)="load()" class="input w-full text-sm">
              <option value="">All types</option>
              @for (t of eventTypes; track t) {
                <option [value]="t">{{ t }}</option>
              }
            </select>
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">Agent ID</label>
            <input [(ngModel)]="filterAgent" (blur)="load()"
                   class="input w-full text-sm font-mono" placeholder="uuid…" />
          </div>
          <div>
            <label class="block text-xs text-slate-400 mb-1">Date (YYYY-MM-DD)</label>
            <input [(ngModel)]="filterDate" (blur)="load()"
                   class="input w-full text-sm" type="date" />
          </div>
        </div>
      </div>

      <!-- Table -->
      @if (loading()) {
        <div class="py-16 text-center text-slate-500 text-sm">Loading…</div>
      } @else if (items().length === 0) {
        <div class="card py-16 text-center">
          <p class="text-slate-400">No audit events found.</p>
        </div>
      } @else {
        <div class="card overflow-hidden p-0">
          <table class="w-full text-sm">
            <thead>
              <tr>
                <th class="table-header">Event</th>
                <th class="table-header">Agent</th>
                <th class="table-header">Tool</th>
                <th class="table-header">Policy</th>
                <th class="table-header text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              @for (ev of items(); track ev.id) {
                <tr class="table-row">
                  <td class="table-cell">
                    <agr-badge [variant]="eventVariant(ev.event_type)">{{ ev.event_type }}</agr-badge>
                  </td>
                  <td class="table-cell font-mono text-xs text-slate-300">
                    {{ ev.agent_id | slice:0:8 }}…
                  </td>
                  <td class="table-cell text-slate-300">{{ ev.tool_name ?? '—' }}</td>
                  <td class="table-cell text-xs text-slate-400">{{ ev.policy_id ? (ev.policy_id | slice:0:8) + '…' : '—' }}</td>
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
          <span>Showing {{ items().length }} events</span>
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

  filterType = '';
  filterAgent = '';
  filterDate = '';

  readonly loading = signal(true);
  readonly offset = signal(0);
  readonly items = signal<AuditEvent[]>([]);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.svc.list({
      event_type: this.filterType || undefined,
      agent_id: this.filterAgent.trim() || undefined,
      date: this.filterDate || undefined,
      limit: this.pageSize,
      offset: this.offset(),
    }).subscribe({
      next: (res) => {
        this.items.set(res.items);
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
}
