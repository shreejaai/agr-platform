import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AgentService } from '../../services/agent.service';
import { ApiKeyService } from '../../services/api-key.service';
import { ApprovalService } from '../../services/approval.service';
import { AuditService } from '../../services/audit.service';
import { OnboardingService } from '../../services/onboarding.service';
import { PolicyService } from '../../services/policy.service';
import { StatCardComponent } from '../../shared/components/stat-card/stat-card.component';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { AuditEvent } from '../../core/models/audit-event.model';

interface OnboardingStep {
  id: 'api-key' | 'agent' | 'policy' | 'evaluation';
  order: number;
  title: string;
  description: string;
  path: string;
  queryParams: { onboarding: string };
  actionLabel: string;
  done: boolean;
}

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

      @if (showOnboarding()) {
        <div class="card border border-indigo-500/20 bg-indigo-500/5">
          <div class="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.25em] text-indigo-300">
                Guided setup
              </p>
              <h2 class="mt-2 text-lg font-semibold text-slate-100">
                Finish your first governed workflow
              </h2>
              <p class="mt-2 text-sm text-slate-400 max-w-3xl">
                Set an API key, register an agent, add a sample policy, and run your first
                evaluation. The setup is non-blocking, and progress is saved as you go.
              </p>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-xs text-slate-400">
                {{ completedOnboardingSteps() }}/{{ onboardingSteps().length }} complete
              </span>
              <button
                type="button"
                (click)="dismissOnboarding()"
                class="text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                Hide for now
              </button>
            </div>
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-2">
            @for (step of onboardingSteps(); track step.id) {
              <a
                [routerLink]="step.path"
                [queryParams]="step.queryParams"
                class="rounded-xl border px-4 py-4 transition-colors"
                [class]="stepCardClass(step.done)"
              >
                <div class="flex items-start gap-3">
                  <span
                    class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
                    [class]="stepBadgeClass(step.done)"
                  >
                    {{ step.done ? 'Done' : step.order }}
                  </span>
                  <div class="min-w-0">
                    <p class="text-sm font-semibold text-slate-100">{{ step.title }}</p>
                    <p class="mt-1 text-xs text-slate-400">{{ step.description }}</p>
                    <p class="mt-2 text-xs font-medium" [class]="stepActionClass(step.done)">
                      {{ step.done ? 'Complete' : step.actionLabel }}
                    </p>
                  </div>
                </div>
              </a>
            }
          </div>
        </div>
      } @else if (showResumeOnboarding()) {
        <div class="card border border-slate-700/80 bg-slate-900/70">
          <div class="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p class="text-sm font-medium text-slate-100">Setup is still in progress.</p>
              <p class="mt-1 text-xs text-slate-500">
                {{ completedOnboardingSteps() }}/{{ onboardingSteps().length }} onboarding steps complete.
              </p>
            </div>
            <button type="button" (click)="resumeOnboarding()" class="btn-secondary text-sm">
              Resume setup
            </button>
          </div>
        </div>
      }

      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <agr-stat-card label="Pending Approvals" [value]="pendingCount()" sublabel="awaiting decision" />
        <agr-stat-card label="Active Policies" [value]="policyCount()" sublabel="enforced rules" />
        <agr-stat-card label="Events Today" [value]="eventsToday()" sublabel="in audit log" />
        <agr-stat-card label="Allow Rate" [value]="allowRate()" sublabel="last 20 events" />
      </div>

      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-base font-semibold text-slate-100">Recent Audit Events</h2>
          <a routerLink="/audit" class="text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
            View all ->
          </a>
        </div>

        @if (loading()) {
          <div class="py-8 text-center text-slate-500 text-sm">Loading...</div>
        } @else if (recentEvents().length === 0) {
          <div class="py-8 text-center text-slate-500 text-sm">No events yet.</div>
        } @else {
          <table class="w-full text-sm">
            <thead>
              <tr>
                <th class="table-header">Event</th>
                <th class="table-header">Agent</th>
                <th class="table-header">Action</th>
                <th class="table-header text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              @for (ev of recentEvents(); track ev.id) {
                <tr class="table-row">
                  <td class="table-cell">
                    <agr-badge [variant]="eventVariant(ev.event_type)">{{ ev.event_type }}</agr-badge>
                  </td>
                  <td class="table-cell font-mono text-xs text-slate-300 max-w-[100px] truncate">
                    {{ ev.agent_id }}
                  </td>
                  <td class="table-cell text-slate-300">{{ ev.action }}</td>
                  <td class="table-cell text-right text-slate-400">
                    {{ ev.recorded_at | relativeTime }}
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      </div>

      @if (pendingCountNum() > 0) {
        <div class="card border border-amber-500/20 bg-amber-500/5">
          <div class="flex items-center justify-between mb-2">
            <h2 class="text-base font-semibold text-amber-300">
              {{ pendingCountNum() }} Pending Approval{{ pendingCountNum() !== 1 ? 's' : '' }}
            </h2>
            <a routerLink="/approvals" class="text-xs text-amber-400 hover:text-amber-300 transition-colors">
              Review ->
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
  private readonly agentSvc = inject(AgentService);
  private readonly apiKey = inject(ApiKeyService);
  private readonly approvalSvc = inject(ApprovalService);
  private readonly auditSvc = inject(AuditService);
  private readonly onboarding = inject(OnboardingService);
  private readonly policySvc = inject(PolicyService);

  readonly loading = signal(true);
  readonly pendingCount = signal<number | string>('—');
  readonly policyCount = signal<number | string>('—');
  readonly agentCount = signal<number | string>('—');
  readonly eventsToday = signal<number | string>('—');
  readonly allowRate = signal<string>('—');
  readonly recentEvents = signal<AuditEvent[]>([]);

  readonly onboardingSteps = computed<OnboardingStep[]>(() => [
    {
      id: 'api-key',
      order: 1,
      title: 'Save your API key',
      description: 'Store the org API key in this browser so protected dashboard routes can call the AGR API.',
      path: '/settings',
      queryParams: { onboarding: 'api-key' },
      actionLabel: 'Open Settings',
      done: this.apiKey.hasKey(),
    },
    {
      id: 'agent',
      order: 2,
      title: 'Register an agent',
      description: 'Create the first tracked agent identity so approvals, audit logs, and policy checks map to a real actor.',
      path: '/agents',
      queryParams: { onboarding: 'register' },
      actionLabel: 'Register agent',
      done: this.numericValue(this.agentCount()) > 0,
    },
    {
      id: 'policy',
      order: 3,
      title: 'Create a sample policy',
      description: 'Start with a sample rule, then adjust it in the existing policy editor before saving.',
      path: '/policies',
      queryParams: { onboarding: 'sample' },
      actionLabel: 'Create sample policy',
      done: this.numericValue(this.policyCount()) > 0,
    },
    {
      id: 'evaluation',
      order: 4,
      title: 'Run your first evaluation',
      description: 'Use the simulator to exercise the full decision path and confirm the first workflow end to end.',
      path: '/simulator',
      queryParams: { onboarding: 'first-eval' },
      actionLabel: 'Open simulator',
      done: this.recentEvents().length > 0,
    },
  ]);

  readonly completedOnboardingSteps = computed(
    () => this.onboardingSteps().filter((step) => step.done).length,
  );

  readonly allOnboardingStepsComplete = computed(
    () => this.onboardingSteps().every((step) => step.done),
  );

  readonly showOnboarding = computed(
    () => !this.allOnboardingStepsComplete() && !this.onboarding.dismissed(),
  );

  readonly showResumeOnboarding = computed(
    () => !this.allOnboardingStepsComplete() && this.onboarding.dismissed(),
  );

  pendingCountNum(): number {
    return this.numericValue(this.pendingCount());
  }

  ngOnInit(): void {
    this.approvalSvc.list({ status: 'pending', limit: 100 }).subscribe({
      next: (approvals) => this.pendingCount.set(approvals.length),
      error: () => this.pendingCount.set('—'),
    });

    this.policySvc.list({ limit: 100 }).subscribe({
      next: (policies) => this.policyCount.set(policies.filter((policy) => policy.active).length),
      error: () => this.policyCount.set('—'),
    });

    this.agentSvc.list({ limit: 100 }).subscribe({
      next: (agents) => this.agentCount.set(agents.length),
      error: () => this.agentCount.set('—'),
    });

    const today = new Date().toISOString().slice(0, 10);
    this.auditSvc.list({ limit: 20 }).subscribe({
      next: (events) => {
        this.recentEvents.set(events);
        this.eventsToday.set(events.filter((event) => event.recorded_at.startsWith(today)).length);
        const allows = events.filter((event) => event.event_type === 'TOOL_ALLOW').length;
        this.allowRate.set(events.length ? `${Math.round((allows / events.length) * 100)}%` : '—');
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  dismissOnboarding(): void {
    this.onboarding.dismiss();
  }

  resumeOnboarding(): void {
    this.onboarding.resume();
  }

  stepCardClass(done: boolean): string {
    return done
      ? 'border-emerald-500/20 bg-emerald-500/5 hover:bg-emerald-500/10'
      : 'border-slate-700 bg-slate-900/70 hover:border-indigo-500/40 hover:bg-slate-900';
  }

  stepBadgeClass(done: boolean): string {
    return done
      ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
      : 'bg-indigo-500/15 text-indigo-300 border border-indigo-500/30';
  }

  stepActionClass(done: boolean): string {
    return done ? 'text-emerald-300' : 'text-indigo-300';
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

  private numericValue(value: number | string): number {
    return typeof value === 'number' ? value : 0;
  }
}
