import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApprovalService } from '../../services/approval.service';
import { PolicyService } from '../../services/policy.service';
import { AuditService } from '../../services/audit.service';
import { StatCardComponent } from '../../shared/components/stat-card/stat-card.component';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { AuditEvent } from '../../models/audit-event.model';

@Component({
  selector: 'agr-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, StatCardComponent, BadgeComponent, RelativeTimePipe],
  template: `
    <div class="space-y-6">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">Overview</h1>
        <p class="text-sm text-slate-400 mt-1">Real-time governance metrics for your AI agents.</p>
      </div>

      <!-- Stat cards -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <agr-stat-card
          label="Pending Approvals"
          [value]="pendingCount()"
          sublabel="awaiting decision"
        />
        <agr-stat-card
          label="Active Policies"
          [value]="policyCount()"
          sublabel="enforced rules"
        />
        <agr-stat-card
          label="Events Today"
          [value]="eventsToday()"
          sublabel="in audit log"
        />
        <agr-stat-card
          label="Allow Rate"
          [value]="allowRate()"
          sublabel="last 100 events"
        />
      </div>

      <!-- Recent audit events -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-base font-semibold text-slate-100">Recent Audit Events</h2>
          <a routerLink="/audit" class="text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
            View all →
          </a>
        </div>

        @if (loading()) {
          <div class="py-8 text-center text-slate-500 text-sm">Loading…</div>
        } @else if (recentEvents().length === 0) {
          <div class="py-8 text-center text-slate-500 text-sm">No events yet.</div>
        } @else {
          <table class="w-full text-sm">
            <thead>
              <tr>
                <th class="table-header">Event</th>
                <th class="table-header">Agent</th>
                <th class="table-header">Tool</th>
                <th class="table-header text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              @for (ev of recentEvents(); track ev.id) {
                <tr class="table-row">
                  <td class="table-cell">
                    <agr-badge [variant]="eventVariant(ev.event_type)">
                      {{ ev.event_type }}
                    </agr-badge>
                  </td>
                  <td class="table-cell font-mono text-xs text-slate-300">
                    {{ ev.agent_id | slice:0:8 }}…
                  </td>
                  <td class="table-cell text-slate-300">{{ ev.tool_name ?? '—' }}</td>
                  <td class="table-cell text-right text-slate-400">
                    {{ ev.recorded_at | relativeTime }}
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      </div>

      <!-- Pending approvals quick list -->
      @if (pendingCount() > 0) {
        <div class="card border border-amber-500/20 bg-amber-500/5">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-base font-semibold text-amber-300">
              {{ pendingCount() }} Pending Approval{{ pendingCount() !== 1 ? 's' : '' }}
            </h2>
            <a routerLink="/approvals" class="text-xs text-amber-400 hover:text-amber-300 transition-colors">
              Review →
            </a>
          </div>
          <p class="text-xs text-slate-400">
            Agent tool calls are waiting for human approval before proceeding.
          </p>
        </div>
      }
    </div>
  `,
})
export class HomeComponent implements OnInit {
  private approvalSvc = inject(ApprovalService);
  private policySvc = inject(PolicyService);
  private auditSvc = inject(AuditService);

  readonly loading = signal(true);
  readonly pendingCount = signal<number | string>('—');
  readonly policyCount = signal<number | string>('—');
  readonly eventsToday = signal<number | string>('—');
  readonly allowRate = signal<string>('—');
  readonly recentEvents = signal<AuditEvent[]>([]);

  ngOnInit(): void {
    this.approvalSvc.list({ status: 'pending', limit: 100 }).subscribe({
      next: (res) => this.pendingCount.set(res.items.length),
      error: () => this.pendingCount.set('—'),
    });

    this.policySvc.list({ limit: 100 }).subscribe({
      next: (res) => this.policyCount.set(res.items.length),
      error: () => this.policyCount.set('—'),
    });

    this.auditSvc.list({ limit: 20 }).subscribe({
      next: (res) => {
        this.recentEvents.set(res.items);
        const today = new Date().toISOString().slice(0, 10);
        this.eventsToday.set(res.items.filter((e) => e.recorded_at.startsWith(today)).length);
        const allows = res.items.filter((e) => e.event_type === 'TOOL_ALLOW').length;
        this.allowRate.set(res.items.length ? `${Math.round((allows / res.items.length) * 100)}%` : '—');
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
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
}
