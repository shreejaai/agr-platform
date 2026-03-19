import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApprovalService } from '../../services/approval.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { Approval } from '../../core/models/approval.model';

type StatusFilter = 'pending' | 'approved' | 'rejected' | '';

@Component({
  selector: 'agr-approvals',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, BadgeComponent, RelativeTimePipe],
  template: `
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-slate-100">Approvals</h1>
          <p class="text-sm text-slate-400 mt-1">Review and decide on pending agent tool calls.</p>
        </div>
        <select [(ngModel)]="statusFilter" (ngModelChange)="load()" class="input text-sm w-36">
          <option value="">All</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      @if (loading()) {
        <div class="py-16 text-center text-slate-500 text-sm">Loading…</div>
      } @else if (items().length === 0) {
        <div class="card py-16 text-center">
          <p class="text-slate-400">No approvals found.</p>
          <p class="text-slate-500 text-xs mt-1">Pending tool calls from AI agents will appear here.</p>
        </div>
      } @else {
        <div class="space-y-3">
          @for (item of items(); track item.id) {
            <div class="card hover:border-slate-700 transition-colors"
                 [class.border-amber-500/30]="item.status === 'pending'">
              <div class="flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-1">
                    <agr-badge [variant]="statusVariant(item.status)">{{ item.status }}</agr-badge>
                    <span class="text-xs text-slate-500">{{ item.created_at | relativeTime }}</span>
                  </div>

                  <!-- action is the tool name -->
                  <p class="text-sm font-medium text-slate-200">
                    Action: <span class="font-mono text-indigo-300">{{ item.action }}</span>
                    on <span class="font-mono text-slate-300">{{ item.resource }}</span>
                  </p>
                  <p class="text-xs text-slate-400 mt-0.5 truncate">
                    Agent: <span class="font-mono">{{ item.agent_id }}</span>
                  </p>

                  @if (item.approver_email) {
                    <p class="text-xs text-slate-500 mt-0.5">
                      Approver: {{ item.approver_email }}
                    </p>
                  }

                  <!-- context is the tool input equivalent -->
                  @if (item.context && objectKeys(item.context).length > 0) {
                    <details class="mt-2">
                      <summary class="text-xs text-slate-500 cursor-pointer hover:text-slate-300">
                        Context / tool input
                      </summary>
                      <pre class="mt-1 text-xs bg-slate-900 rounded p-2 overflow-x-auto text-slate-300">{{
                        item.context | json
                      }}</pre>
                    </details>
                  }

                  <!-- escalate form for pending items without approver -->
                  @if (item.status === 'pending' && !item.approver_email) {
                    @if (escalatingId() === item.id) {
                      <div class="mt-2 flex items-center gap-2">
                        <input
                          [(ngModel)]="escalateEmail"
                          type="email"
                          placeholder="approver@example.com"
                          class="input text-xs flex-1"
                        />
                        <button
                          (click)="escalate(item.id)"
                          class="px-2 py-1 text-xs rounded bg-slate-700 text-slate-200 hover:bg-slate-600"
                        >Send</button>
                        <button
                          (click)="escalatingId.set(null)"
                          class="text-xs text-slate-500 hover:text-slate-300"
                        >Cancel</button>
                      </div>
                    }
                  }
                </div>

                <div class="flex flex-col gap-1.5 shrink-0">
                  @if (item.status === 'pending') {
                    <button
                      (click)="decide(item.id, 'approve')"
                      [disabled]="deciding() === item.id"
                      class="px-3 py-1.5 text-xs font-medium rounded-lg
                             bg-green-500/15 text-green-400 border border-green-500/30
                             hover:bg-green-500/25 disabled:opacity-50 transition-colors"
                    >Approve</button>
                    <button
                      (click)="decide(item.id, 'reject')"
                      [disabled]="deciding() === item.id"
                      class="px-3 py-1.5 text-xs font-medium rounded-lg
                             bg-red-500/15 text-red-400 border border-red-500/30
                             hover:bg-red-500/25 disabled:opacity-50 transition-colors"
                    >Reject</button>
                    <button
                      (click)="escalatingId.set(item.id); escalateEmail = ''"
                      class="px-3 py-1.5 text-xs font-medium rounded-lg
                             bg-slate-700 text-slate-300 border border-slate-600
                             hover:bg-slate-600 transition-colors"
                    >Escalate</button>
                  }
                </div>
              </div>
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class ApprovalsComponent implements OnInit {
  private svc = inject(ApprovalService);

  statusFilter: StatusFilter = 'pending';
  escalateEmail = '';

  readonly loading = signal(true);
  readonly deciding = signal<string | null>(null);
  readonly escalatingId = signal<string | null>(null);
  readonly items = signal<Approval[]>([]);
  readonly objectKeys = Object.keys;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    const params = this.statusFilter ? { status: this.statusFilter, limit: 50 } : { limit: 50 };
    this.svc.list(params).subscribe({
      next: (res) => {
        this.items.set(res);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  decide(id: string, action: 'approve' | 'reject'): void {
    this.deciding.set(id);
    const call = action === 'approve' ? this.svc.approve(id) : this.svc.reject(id);
    call.subscribe({
      next: (updated) => {
        this.items.update((list) => list.map((a) => (a.id === id ? updated : a)));
        this.deciding.set(null);
      },
      error: () => this.deciding.set(null),
    });
  }

  escalate(id: string): void {
    if (!this.escalateEmail.trim()) return;
    this.svc.escalate(id, this.escalateEmail.trim()).subscribe({
      next: (updated) => {
        this.items.update((list) => list.map((a) => (a.id === id ? updated : a)));
        this.escalatingId.set(null);
      },
    });
  }

  statusVariant(status: string): 'warning' | 'success' | 'danger' | 'neutral' {
    const map: Record<string, 'warning' | 'success' | 'danger' | 'neutral'> = {
      pending: 'warning',
      approved: 'success',
      rejected: 'danger',
    };
    return map[status] ?? 'neutral';
  }
}
