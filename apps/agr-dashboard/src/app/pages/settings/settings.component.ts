import { Component, inject, ChangeDetectionStrategy, signal, OnInit } from '@angular/core';
import { FormsModule, DecimalPipe } from '@angular/common';
import { ApiKeyService } from '../../services/api-key.service';
import { OrgService, OrgMe } from '../../services/org.service';

@Component({
  selector: 'agr-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DecimalPipe],
  template: `
    <div class="max-w-2xl mx-auto">
      <h1 class="text-2xl font-bold text-slate-100 mb-6">Settings</h1>

      <!-- Org Info -->
      @if (org()) {
        <div class="card mb-6">
          <h2 class="text-base font-semibold text-slate-100 mb-3">Organization</h2>
          <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt class="text-slate-400">Name</dt>
            <dd class="text-slate-100 font-medium">{{ org()!.name }}</dd>

            <dt class="text-slate-400">Plan</dt>
            <dd>
              <span class="px-2 py-0.5 rounded-full text-xs font-semibold uppercase
                           bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                {{ org()!.plan }}
              </span>
            </dd>

            <dt class="text-slate-400">Evaluations</dt>
            <dd class="text-slate-100">
              @if (org()!.eval_limit === 0) {
                {{ org()!.eval_count | number }} / Unlimited
              } @else {
                {{ org()!.eval_count | number }} / {{ org()!.eval_limit | number }}
              }
            </dd>

            @if (org()!.eval_limit > 0) {
              <dt class="text-slate-400">Usage</dt>
              <dd class="flex items-center gap-2">
                <div class="flex-1 h-1.5 rounded-full bg-slate-700 overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all"
                    [class]="usageBarClass()"
                    [style.width.%]="usagePct()"
                  ></div>
                </div>
                <span class="text-xs text-slate-400">{{ usagePct() }}%</span>
              </dd>
            }
          </dl>
        </div>
      }

      <!-- API Key -->
      <div class="card mb-6">
        <h2 class="text-base font-semibold text-slate-100 mb-1">API Key</h2>
        <p class="text-sm text-slate-400 mb-4">
          Your <code class="text-indigo-300 bg-slate-800 px-1 rounded">agr_sk_</code> secret key is
          used to authenticate requests to the AGR API. It is stored only in this browser.
        </p>

        @if (saved()) {
          <div class="mb-3 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/20">
            <p class="text-sm text-green-400">API key saved successfully.</p>
          </div>
        }

        @if (error()) {
          <div class="mb-3 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
            <p class="text-sm text-red-400">{{ error() }}</p>
          </div>
        }

        <div class="space-y-3">
          <input
            type="password"
            [(ngModel)]="keyInput"
            placeholder="agr_sk_…"
            class="input w-full font-mono"
            autocomplete="off"
          />

          <div class="flex items-center gap-3">
            <button (click)="save()" class="btn-primary">Save key</button>
            @if (hasKey()) {
              <button
                (click)="clear()"
                class="px-3 py-1.5 text-sm text-red-400 border border-red-500/30
                       rounded-lg hover:bg-red-500/10 transition-colors"
              >
                Remove key
              </button>
            }
          </div>
        </div>

        @if (hasKey()) {
          <div class="mt-4 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-green-400"></span>
            <span class="text-xs text-slate-400">API key configured</span>
          </div>
        }
      </div>

      <!-- About -->
      <div class="card">
        <h2 class="text-base font-semibold text-slate-100 mb-1">About</h2>
        <p class="text-sm text-slate-400">
          AGR Dashboard — Agentic Governance Runtime v0.1
        </p>
        <p class="text-xs text-slate-500 mt-2">
          Manage AI agent policies, approve pending tool calls, and view audit logs.
        </p>
      </div>
    </div>
  `,
})
export class SettingsComponent implements OnInit {
  private apiKey = inject(ApiKeyService);
  private orgSvc = inject(OrgService);

  keyInput = this.apiKey.getKey() ?? '';
  readonly hasKey = this.apiKey.hasKey.bind(this.apiKey);
  readonly saved = signal(false);
  readonly error = signal('');
  readonly org = signal<OrgMe | null>(null);

  ngOnInit(): void {
    if (this.hasKey()) {
      this.orgSvc.getMe().subscribe({ next: (o) => this.org.set(o) });
    }
  }

  usagePct(): number {
    const o = this.org();
    if (!o || o.eval_limit === 0) return 0;
    return Math.min(100, Math.round((o.eval_count / o.eval_limit) * 100));
  }

  usageBarClass(): string {
    const pct = this.usagePct();
    if (pct >= 90) return 'bg-red-500';
    if (pct >= 70) return 'bg-amber-400';
    return 'bg-indigo-500';
  }

  save(): void {
    const trimmed = this.keyInput.trim();
    if (!trimmed.startsWith('agr_sk_')) {
      this.error.set('Key must start with agr_sk_');
      return;
    }
    this.apiKey.setKey(trimmed);
    this.error.set('');
    this.saved.set(true);
    setTimeout(() => this.saved.set(false), 3000);
    this.orgSvc.getMe().subscribe({ next: (o) => this.org.set(o) });
  }

  clear(): void {
    this.apiKey.clearKey();
    this.keyInput = '';
    this.saved.set(false);
    this.org.set(null);
  }
}
