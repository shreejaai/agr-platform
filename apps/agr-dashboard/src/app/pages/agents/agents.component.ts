import { Component, inject, OnInit, ChangeDetectionStrategy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AgentService } from '../../services/agent.service';
import { BadgeComponent } from '../../shared/components/badge/badge.component';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';
import { Agent, AgentRegister } from '../../models/agent.model';

@Component({
  selector: 'agr-agents',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, BadgeComponent, RelativeTimePipe],
  template: `
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-slate-100">Agents</h1>
          <p class="text-sm text-slate-400 mt-1">Registered AI agents making governed tool calls.</p>
        </div>
        <button (click)="showForm.set(true)" class="btn-primary text-sm">+ Register agent</button>
      </div>

      <!-- Register form -->
      @if (showForm()) {
        <div class="card border border-indigo-500/30">
          <h2 class="text-base font-semibold text-slate-100 mb-4">Register Agent</h2>
          <div class="space-y-3">
            <div>
              <label class="block text-xs text-slate-400 mb-1">Agent ID</label>
              <input [(ngModel)]="form.agent_id" class="input w-full font-mono"
                     placeholder="my-langchain-agent-v1" />
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Name</label>
              <input [(ngModel)]="form.name" class="input w-full" placeholder="Research Assistant" />
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Description (optional)</label>
              <input [(ngModel)]="form.description" class="input w-full"
                     placeholder="LangGraph agent for market research" />
            </div>
            <div>
              <label class="block text-xs text-slate-400 mb-1">Framework</label>
              <select [(ngModel)]="form.framework" class="input w-full">
                <option value="">— Select —</option>
                <option value="langchain">LangChain</option>
                <option value="langgraph">LangGraph</option>
                <option value="crewai">CrewAI</option>
                <option value="autogen">AutoGen</option>
                <option value="custom">Custom</option>
              </select>
            </div>

            @if (formError()) {
              <p class="text-sm text-red-400">{{ formError() }}</p>
            }
            @if (registeredKey()) {
              <div class="p-3 rounded-lg bg-green-500/10 border border-green-500/20">
                <p class="text-xs text-green-400 mb-1 font-medium">Agent registered! Save this key — it won't be shown again.</p>
                <code class="text-xs font-mono text-slate-200 break-all">{{ registeredKey() }}</code>
              </div>
            }

            <div class="flex gap-2">
              <button (click)="register()" [disabled]="saving()" class="btn-primary text-sm">
                {{ saving() ? 'Registering…' : 'Register' }}
              </button>
              <button (click)="cancelForm()"
                      class="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors">
                {{ registeredKey() ? 'Done' : 'Cancel' }}
              </button>
            </div>
          </div>
        </div>
      }

      <!-- List -->
      @if (loading()) {
        <div class="py-16 text-center text-slate-500 text-sm">Loading…</div>
      } @else if (items().length === 0) {
        <div class="card py-16 text-center">
          <p class="text-slate-400">No agents registered yet.</p>
          <p class="text-slate-500 text-xs mt-1">Register your first agent to start tracking its tool calls.</p>
        </div>
      } @else {
        <div class="card overflow-hidden p-0">
          <table class="w-full text-sm">
            <thead>
              <tr>
                <th class="table-header">Agent</th>
                <th class="table-header">Framework</th>
                <th class="table-header">Status</th>
                <th class="table-header text-right">Registered</th>
              </tr>
            </thead>
            <tbody>
              @for (a of items(); track a.id) {
                <tr class="table-row">
                  <td class="table-cell">
                    <div class="font-medium text-slate-200">{{ a.name }}</div>
                    <div class="text-xs font-mono text-slate-500">{{ a.agent_id }}</div>
                    @if (a.description) {
                      <div class="text-xs text-slate-500 mt-0.5">{{ a.description }}</div>
                    }
                  </td>
                  <td class="table-cell text-slate-400">{{ a.framework ?? '—' }}</td>
                  <td class="table-cell">
                    <agr-badge [variant]="a.is_active ? 'success' : 'neutral'">
                      {{ a.is_active ? 'active' : 'inactive' }}
                    </agr-badge>
                  </td>
                  <td class="table-cell text-right text-slate-400">
                    {{ a.created_at | relativeTime }}
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </div>
  `,
})
export class AgentsComponent implements OnInit {
  private svc = inject(AgentService);

  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly showForm = signal(false);
  readonly formError = signal('');
  readonly registeredKey = signal('');
  readonly items = signal<Agent[]>([]);

  form: AgentRegister = this.emptyForm();

  ngOnInit(): void {
    this.loadList();
  }

  loadList(): void {
    this.svc.list({ limit: 100 }).subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  register(): void {
    if (!this.form.agent_id.trim() || !this.form.name.trim()) {
      this.formError.set('Agent ID and name are required.');
      return;
    }
    this.saving.set(true);
    this.formError.set('');
    this.svc.register(this.form).subscribe({
      next: (res) => {
        this.saving.set(false);
        if (res.api_key) {
          this.registeredKey.set(res.api_key);
        }
        this.loadList();
      },
      error: () => {
        this.formError.set('Registration failed. Please try again.');
        this.saving.set(false);
      },
    });
  }

  cancelForm(): void {
    this.showForm.set(false);
    this.form = this.emptyForm();
    this.formError.set('');
    this.registeredKey.set('');
  }

  private emptyForm(): AgentRegister {
    return { agent_id: '', name: '', description: '', framework: '' };
  }
}
