import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ComplianceFinding } from '../../../core/models/compliance.model';

@Component({
  selector: 'agr-compliance-findings',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (allFindings().length > 0) {
      <div class="space-y-4">
        <div class="rounded-lg border border-slate-700 bg-slate-900/70 px-4 py-4">
          <div class="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p class="text-xs uppercase tracking-[0.2em] text-slate-500">Compliance</p>
              <p class="mt-2 text-sm text-slate-200">
                {{ passedCount() }}/{{ allFindings().length }} controls passing
              </p>
              <p class="mt-1 text-xs text-slate-500">
                Deterministic remediation guidance derived from violated controls and risk factors.
              </p>
            </div>
            <div class="text-right">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-500">Avg score</p>
              <p class="mt-2 text-2xl font-semibold" [ngClass]="scoreClass(averageScore())">
                {{ averageScore() ?? '—' }}
              </p>
            </div>
          </div>
        </div>

        @if (violations().length > 0) {
          <div class="space-y-3">
            @for (finding of violations(); track finding.rule_id + '-' + finding.message) {
              <div class="rounded-lg border border-slate-700 bg-slate-950/70 px-4 py-4">
                <div class="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <p class="text-xs uppercase tracking-[0.2em] text-slate-500">
                      {{ finding.standard }} / {{ finding.rule_id }}
                    </p>
                    <p class="mt-2 text-sm font-medium text-slate-100">{{ finding.message }}</p>
                  </div>
                  <div class="flex items-center gap-2 flex-wrap">
                    <span
                      class="inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-wide"
                      [ngClass]="severityClass(finding.severity_level)"
                    >
                      {{ finding.severity_level ?? 'low' }}
                    </span>
                    <span
                      class="inline-flex items-center rounded-full border border-slate-700 px-3 py-1 text-xs font-semibold"
                      [ngClass]="scoreClass(finding.compliance_score)"
                    >
                      {{ finding.compliance_score ?? 100 }}/100
                    </span>
                  </div>
                </div>

                @if (remediationSteps(finding).length > 0) {
                  <div class="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3">
                    <p class="text-xs uppercase tracking-[0.2em] text-amber-200/80">
                      Remediation steps
                    </p>
                    <ol class="mt-2 list-decimal space-y-1 pl-5 text-sm text-amber-50/90">
                      @for (step of remediationSteps(finding); track step) {
                        <li>{{ step }}</li>
                      }
                    </ol>
                  </div>
                }
              </div>
            }
          </div>
        } @else {
          <div class="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
            <p class="text-sm font-medium text-emerald-200">All returned compliance checks passed.</p>
            <p class="mt-1 text-xs text-emerald-100/80">
              No remediation is required for this simulation result.
            </p>
          </div>
        }
      </div>
    } @else {
      <div class="rounded-lg border border-slate-700 bg-slate-900/60 px-4 py-3">
        <p class="text-sm text-slate-300">No compliance findings returned.</p>
      </div>
    }
  `,
})
export class ComplianceFindingsComponent {
  @Input() findings: ComplianceFinding[] | null = null;

  allFindings(): ComplianceFinding[] {
    return Array.isArray(this.findings) ? this.findings : [];
  }

  violations(): ComplianceFinding[] {
    return this.allFindings().filter((finding) => !finding.passed);
  }

  passedCount(): number {
    return this.allFindings().filter((finding) => finding.passed).length;
  }

  averageScore(): number | null {
    const scores = this.allFindings()
      .map((finding) => finding.compliance_score)
      .filter((score): score is number => typeof score === 'number');
    if (scores.length === 0) {
      return null;
    }
    return Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length);
  }

  remediationSteps(finding: ComplianceFinding): string[] {
    return Array.isArray(finding.remediation_steps) ? finding.remediation_steps : [];
  }

  severityClass(level: string | undefined): string {
    switch (level) {
      case 'critical':
        return 'border-red-500/30 bg-red-500/15 text-red-200';
      case 'high':
        return 'border-orange-500/30 bg-orange-500/15 text-orange-200';
      case 'medium':
        return 'border-amber-500/30 bg-amber-500/15 text-amber-200';
      default:
        return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-200';
    }
  }

  scoreClass(score: number | null | undefined): string {
    if (typeof score !== 'number') {
      return 'text-slate-300';
    }
    if (score < 40) {
      return 'text-red-300';
    }
    if (score < 70) {
      return 'text-amber-300';
    }
    return 'text-emerald-300';
  }
}
