import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { agentName, Agent } from '../../core/models/agent.model';
import { AgentService } from '../../services/agent.service';
import { PolicyService, SimulateResult } from '../../services/policy.service';
import { RiskBreakdownComponent } from '../../shared/components/risk-breakdown/risk-breakdown.component';

interface ContextEntry {
  key: string;
  value: string;
}

type DecisionTone = 'allow' | 'deny' | 'approval';

@Component({
  selector: 'agr-policy-simulator',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, RiskBreakdownComponent],
  templateUrl: './policy-simulator.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PolicySimulatorComponent implements OnInit {
  private readonly policyService = inject(PolicyService);
  private readonly agentService = inject(AgentService);
  private readonly route = inject(ActivatedRoute);

  readonly agentId = signal('');
  readonly action = signal('');
  readonly resource = signal('');
  readonly contextEntries = signal<ContextEntry[]>([{ key: '', value: '' }]);

  readonly loading = signal(false);
  readonly result = signal<SimulateResult | null>(null);
  readonly error = signal<string | null>(null);
  readonly validationErrors = signal<string[]>([]);

  readonly agentsLoading = signal(true);
  readonly agentLoadError = signal<string | null>(null);
  readonly agents = signal<Agent[]>([]);

  readonly canSimulate = computed(
    () =>
      !this.loading() &&
      this.agentId().trim().length > 0 &&
      this.action().trim().length > 0 &&
      this.resource().trim().length > 0,
  );

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('onboarding') === 'first-eval') {
      this.prefillFirstEvaluation();
    }
    this.loadAgents();
  }

  addContextRow(): void {
    this.contextEntries.update((rows) => [...rows, { key: '', value: '' }]);
  }

  removeContextRow(index: number): void {
    this.contextEntries.update((rows) => rows.filter((_, rowIndex) => rowIndex !== index));
  }

  updateContextKey(index: number, value: string): void {
    this.contextEntries.update((rows) =>
      rows.map((row, rowIndex) => (rowIndex === index ? { ...row, key: value } : row)),
    );
  }

  updateContextValue(index: number, value: string): void {
    this.contextEntries.update((rows) =>
      rows.map((row, rowIndex) => (rowIndex === index ? { ...row, value } : row)),
    );
  }

  resetForm(): void {
    this.agentId.set('');
    this.action.set('');
    this.resource.set('');
    this.contextEntries.set([{ key: '', value: '' }]);
    this.result.set(null);
    this.error.set(null);
    this.validationErrors.set([]);
  }

  simulate(): void {
    const validationErrors = this.validate();
    if (validationErrors.length > 0) {
      this.validationErrors.set(validationErrors);
      this.error.set(null);
      this.result.set(null);
      return;
    }

    const context = this.buildContext();
    if ('error' in context) {
      this.validationErrors.set([context.error]);
      this.error.set(null);
      this.result.set(null);
      return;
    }

    this.validationErrors.set([]);
    this.loading.set(true);
    this.result.set(null);
    this.error.set(null);

    this.policyService
      .simulatePolicy({
        agent_id: this.agentId().trim(),
        action: this.action().trim(),
        resource: this.resource().trim(),
        context: context.value,
      })
      .subscribe({
        next: (response) => {
          this.result.set(response);
          this.loading.set(false);
        },
        error: (err: { error?: { detail?: string; message?: string } }) => {
          this.error.set(
            err?.error?.detail ??
              err?.error?.message ??
              'Simulation failed. Check the request and try again.',
          );
          this.loading.set(false);
        },
      });
  }

  decisionTone(decision: string | undefined): DecisionTone {
    if (decision === 'DENY') {
      return 'deny';
    }
    if (decision === 'APPROVAL_REQUIRED') {
      return 'approval';
    }
    return 'allow';
  }

  decisionBadgeClass(decision: string | undefined): string {
    switch (this.decisionTone(decision)) {
      case 'deny':
        return 'bg-red-500/15 text-red-300 border-red-500/30';
      case 'approval':
        return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
      default:
        return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
    }
  }

  decisionPanelClass(decision: string | undefined): string {
    switch (this.decisionTone(decision)) {
      case 'deny':
        return 'border-red-500/20 bg-red-500/5';
      case 'approval':
        return 'border-amber-500/20 bg-amber-500/5';
      default:
        return 'border-emerald-500/20 bg-emerald-500/5';
    }
  }

  riskLevelClass(level: string | null | undefined): string {
    switch (level) {
      case 'critical':
        return 'bg-red-500/15 text-red-300 border-red-500/30';
      case 'high':
        return 'bg-orange-500/15 text-orange-300 border-orange-500/30';
      case 'medium':
        return 'bg-amber-500/15 text-amber-300 border-amber-500/30';
      case 'low':
        return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30';
      default:
        return 'bg-slate-700 text-slate-300 border-slate-600';
    }
  }

  matchedPolicyId(result: SimulateResult | null): string | null {
    return result?.policy_id ?? result?.decision_trace?.matched_policy_id ?? null;
  }

  displayAgentName(agent: Agent): string {
    return agentName(agent);
  }

  private loadAgents(): void {
    this.agentsLoading.set(true);
    this.agentLoadError.set(null);

    this.agentService.list({ limit: 100 }).subscribe({
      next: (agents) => {
        this.agents.set(agents);
        if (agents.length === 1 && !this.agentId().trim()) {
          this.agentId.set(agents[0].agent_id);
        }
        if (!this.agentId().trim() && agents.length > 0 && this.route.snapshot.queryParamMap.get('onboarding') === 'first-eval') {
          this.agentId.set(agents[0].agent_id);
        }
        this.agentsLoading.set(false);
      },
      error: () => {
        this.agentLoadError.set(
          'Unable to load registered agents right now. You can still type an agent ID manually.',
        );
        this.agentsLoading.set(false);
      },
    });
  }

  private validate(): string[] {
    const errors: string[] = [];

    if (!this.agentId().trim()) {
      errors.push('Agent is required.');
    }
    if (!this.action().trim()) {
      errors.push('Action is required.');
    }
    if (!this.resource().trim()) {
      errors.push('Resource is required.');
    }

    const seenKeys = new Set<string>();
    let populatedRows = 0;
    for (const [index, entry] of this.contextEntries().entries()) {
      const key = entry.key.trim();
      const value = entry.value.trim();
      if (!key && !value) {
        continue;
      }
      populatedRows += 1;
      if (!key) {
        errors.push(`Context row ${index + 1} is missing a key.`);
        continue;
      }
      if (seenKeys.has(key)) {
        errors.push(`Context key "${key}" is duplicated.`);
        continue;
      }
      seenKeys.add(key);
    }

    if (populatedRows > 50) {
      errors.push('Context can include at most 50 keys.');
    }

    return errors;
  }

  private buildContext(): { value: Record<string, unknown> } | { error: string } {
    const context: Record<string, unknown> = {};

    for (const [index, entry] of this.contextEntries().entries()) {
      const key = entry.key.trim();
      if (!key) {
        continue;
      }

      const parsed = this.parseContextValue(entry.value);
      if ('error' in parsed) {
        return { error: `Context row ${index + 1}: ${parsed.error}` };
      }
      context[key] = parsed.value;
    }

    return { value: context };
  }

  private parseContextValue(value: string): { value: unknown } | { error: string } {
    const trimmed = value.trim();
    if (!trimmed) {
      return { value: '' };
    }

    if (trimmed === 'true') {
      return { value: true };
    }
    if (trimmed === 'false') {
      return { value: false };
    }
    if (trimmed === 'null') {
      return { value: null };
    }
    if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
      return { value: Number(trimmed) };
    }
    if (
      (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
      (trimmed.startsWith('[') && trimmed.endsWith(']'))
    ) {
      try {
        return { value: JSON.parse(trimmed) as unknown };
      } catch {
        return { error: 'object and array values must be valid JSON.' };
      }
    }

    return { value: value };
  }

  private prefillFirstEvaluation(): void {
    if (!this.agentId().trim()) {
      this.agentId.set('support-agent');
    }
    if (!this.action().trim()) {
      this.action.set('read_ticket_status');
    }
    if (!this.resource().trim()) {
      this.resource.set('ticket-12345');
    }
    if (this.contextEntries().every((entry) => !entry.key && !entry.value)) {
      this.contextEntries.set([
        { key: 'department', value: 'support' },
        { key: 'priority', value: '2' },
      ]);
    }
  }
}
