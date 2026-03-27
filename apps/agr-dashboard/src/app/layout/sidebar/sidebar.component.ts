import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { ClerkService } from '../../core/auth/clerk.service';
import { ApiKeyService } from '../../services/api-key.service';

const NAV_ITEMS = [
  { path: '/home',      label: 'Home',      icon: '⊞' },
  { path: '/approvals', label: 'Approvals', icon: '✓' },
  { path: '/policies',  label: 'Policies',  icon: '🛡' },
  { path: '/audit',     label: 'Audit Log', icon: '📋' },
  { path: '/agents',    label: 'Agents',    icon: '🤖' },
  { path: '/webhooks',  label: 'Webhooks',  icon: '⚡' },
  { path: '/copilot',    label: 'Copilot',    icon: '✦' },
  { path: '/simulator', label: 'Simulator',  icon: '▶' },
  { path: '/team',      label: 'Team',       icon: '👥' },
  { path: '/settings',  label: 'Settings',   icon: '⚙' },
];

@Component({
  selector: 'agr-sidebar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive],
  template: `
    <nav class="w-60 bg-slate-900 h-full flex flex-col border-r border-slate-800 shrink-0">
      <!-- Brand -->
      <div class="px-5 py-5 border-b border-slate-800">
        <div class="flex items-center gap-2">
          <span class="text-indigo-400 font-bold text-lg tracking-tight">AGR</span>
          <span class="text-xs text-slate-500 font-medium">Dashboard</span>
        </div>
        @if (user(); as u) {
          <p class="text-xs text-slate-500 mt-1 truncate">{{ u.email }}</p>
        }
      </div>

      <!-- Nav links -->
      <ul class="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        @for (item of navItems; track item.path) {
          <li>
            <a
              [routerLink]="item.path"
              routerLinkActive="bg-indigo-600/20 text-indigo-400 border-l-2 border-indigo-500"
              [routerLinkActiveOptions]="{ exact: false }"
              class="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-400
                     hover:bg-slate-800 hover:text-slate-200 transition-colors text-sm
                     border-l-2 border-transparent"
            >
              <span class="w-5 text-center">{{ item.icon }}</span>
              {{ item.label }}
            </a>
          </li>
        }
      </ul>

      <!-- Footer -->
      <div class="px-4 py-4 border-t border-slate-800 space-y-2">
        @if (!hasApiKey()) {
          <div class="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <p class="text-xs text-amber-400">API key not set</p>
            <a routerLink="/settings" class="text-xs text-amber-300 underline">Configure →</a>
          </div>
        }
        <button
          (click)="signOut()"
          class="w-full text-left px-3 py-2 text-xs text-slate-500 hover:text-red-400
                 hover:bg-red-500/10 rounded-lg transition-colors"
        >
          Sign out
        </button>
      </div>
    </nav>
  `,
})
export class SidebarComponent {
  private clerk = inject(ClerkService);
  private apiKey = inject(ApiKeyService);

  readonly navItems = NAV_ITEMS;
  readonly user = this.clerk.user;
  readonly hasApiKey = this.apiKey.hasKey.bind(this.apiKey);

  signOut(): void {
    void this.clerk.signOut();
  }
}
