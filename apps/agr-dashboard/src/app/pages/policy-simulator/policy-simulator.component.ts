import {
  Component,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PolicyService, SimulateResult } from '../../services/policy.service';

interface ContextEntry {
  key: string;
  value: string;
}

@Component({
  selector: 'app-policy-simulator',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './policy-simulator.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PolicySimulatorComponent {
  private policyService = inject(PolicyService);

  agentId = signal('');
  action = signal('');
  resource = signal('');
  contextEntries = signal<ContextEntry[]>([{ key: '', value: '' }]);

  loading = signal(false);
  result = signal<SimulateResult | null>(null);
  error = signal<string | null>(null);

  addContextRow(): void {
    this.contextEntries.update((rows) => [...rows, { key: '', value: '' }]);
  }

  removeContextRow(index: number): void {
    this.contextEntries.update((rows) => rows.filter((_, i) => i !== index));
  }

  simulate(): void {
    const context: Record<string, unknown> = {};
    for (const entry of this.contextEntries()) {
      if (entry.key.trim()) {
        context[entry.key.trim()] = entry.value;
      }
    }

    this.loading.set(true);
    this.result.set(null);
    this.error.set(null);

    this.policyService
      .simulatePolicy({
        agent_id: this.agentId(),
        action: this.action(),
        resource: this.resource(),
        context,
      })
      .subscribe({
        next: (res) => {
          this.result.set(res);
          this.loading.set(false);
        },
        error: (err: { error?: { detail?: string } }) => {
          this.error.set(err?.error?.detail ?? 'Simulation failed.');
          this.loading.set(false);
        },
      });
  }

  decisionClass(): string {
    const d = this.result()?.decision;
    if (d === 'ALLOW') return 'text-green-400';
    if (d === 'DENY') return 'text-red-400';
    if (d === 'APPROVAL_REQUIRED') return 'text-yellow-400';
    return '';
  }

  riskFactorEntries(): [string, number][] {
    const rf = this.result()?.risk_factors;
    return rf ? Object.entries(rf) : [];
  }
}
