import { Component, Input, ChangeDetectionStrategy } from '@angular/core';

@Component({
  selector: 'agr-stat-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="card flex flex-col gap-1">
      <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">{{ label }}</span>
      <span class="text-3xl font-bold text-white">{{ value }}</span>
      @if (sublabel) {
        <span class="text-xs text-slate-500">{{ sublabel }}</span>
      }
    </div>
  `,
})
export class StatCardComponent {
  @Input() label = '';
  @Input() value: number | string = 0;
  @Input() sublabel = '';
}
