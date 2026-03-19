import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { NgClass } from '@angular/common';

export type BadgeVariant =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'allow'
  | 'deny'
  | 'requested'
  | 'info'
  | 'org'
  | 'project'
  | 'agent';

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  pending:   'bg-amber-500/20 text-amber-400 border-amber-500/30',
  approved:  'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  rejected:  'bg-red-500/20 text-red-400 border-red-500/30',
  allow:     'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  deny:      'bg-red-500/20 text-red-400 border-red-500/30',
  requested: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  info:      'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  org:       'bg-blue-500/20 text-blue-400 border-blue-500/30',
  project:   'bg-purple-500/20 text-purple-400 border-purple-500/30',
  agent:     'bg-teal-500/20 text-teal-400 border-teal-500/30',
};

@Component({
  selector: 'agr-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgClass],
  template: `
    <span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium border"
          [ngClass]="classes">
      {{ text }}
    </span>
  `,
})
export class BadgeComponent {
  @Input() text = '';
  @Input() variant: BadgeVariant = 'info';

  get classes(): string {
    return VARIANT_CLASSES[this.variant] ?? VARIANT_CLASSES['info'];
  }
}
