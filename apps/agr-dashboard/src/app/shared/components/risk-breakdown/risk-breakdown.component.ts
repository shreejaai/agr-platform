import {
  Component,
  Input,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';

export interface RiskBreakdownData {
  score: number | null;
  level: string | null;
  factors: Record<string, number> | null;
}

@Component({
  selector: 'app-risk-breakdown',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (data && data.score !== null) {
      <div class="space-y-3">
        <!-- Overall score bar -->
        <div class="flex items-center gap-3">
          <div class="flex-1 bg-gray-700 rounded-full h-2">
            <div
              class="h-2 rounded-full transition-all duration-300"
              [class]="scoreBarClass()"
              [style.width.%]="clampedScore()"
            ></div>
          </div>
          <span class="text-sm font-semibold w-10 text-right" [class]="scoreLabelClass()">
            {{ data.score }}<span class="text-gray-500 font-normal">/100</span>
          </span>
          <span
            class="text-xs px-2 py-0.5 rounded-full font-medium uppercase tracking-wide"
            [class]="levelBadgeClass()"
          >{{ data.level ?? '—' }}</span>
        </div>

        <!-- Per-factor breakdown -->
        @if (data.factors && factorEntries().length > 0) {
          <div class="space-y-1.5 mt-2">
            @for (entry of factorEntries(); track entry[0]) {
              <div class="flex items-center gap-2 text-xs">
                <span class="text-gray-400 w-36 truncate capitalize">
                  {{ formatFactor(entry[0]) }}
                </span>
                <div class="flex-1 bg-gray-700 rounded-full h-1.5">
                  <div
                    class="h-1.5 rounded-full"
                    [class]="factorBarClass(entry[1])"
                    [style.width.%]="entry[1]"
                  ></div>
                </div>
                <span class="text-gray-400 w-6 text-right">{{ entry[1] }}</span>
              </div>
            }
          </div>
        }
      </div>
    } @else {
      <span class="text-gray-500 text-sm">—</span>
    }
  `,
})
export class RiskBreakdownComponent {
  @Input() data: RiskBreakdownData | null = null;

  clampedScore(): number {
    return Math.min(100, Math.max(0, this.data?.score ?? 0));
  }

  scoreBarClass(): string {
    const s = this.data?.score ?? 0;
    if (s > 70) return 'bg-red-500';
    if (s > 30) return 'bg-yellow-400';
    return 'bg-green-500';
  }

  scoreLabelClass(): string {
    const s = this.data?.score ?? 0;
    if (s > 70) return 'text-red-400';
    if (s > 30) return 'text-yellow-400';
    return 'text-green-400';
  }

  levelBadgeClass(): string {
    switch (this.data?.level) {
      case 'critical': return 'bg-red-900 text-red-300';
      case 'high':     return 'bg-orange-900 text-orange-300';
      case 'medium':   return 'bg-yellow-900 text-yellow-300';
      case 'low':      return 'bg-green-900 text-green-300';
      default:         return 'bg-gray-700 text-gray-400';
    }
  }

  factorBarClass(value: number): string {
    if (value > 70) return 'bg-red-500';
    if (value > 30) return 'bg-yellow-400';
    return 'bg-indigo-400';
  }

  factorEntries(): [string, number][] {
    return this.data?.factors ? Object.entries(this.data.factors) : [];
  }

  formatFactor(key: string): string {
    return key.replace(/_/g, ' ');
  }
}
