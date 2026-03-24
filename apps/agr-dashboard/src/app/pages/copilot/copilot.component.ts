import {
  Component,
  ChangeDetectionStrategy,
  signal,
  inject,
  AfterViewChecked,
  ElementRef,
  ViewChild,
  OnInit,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CopilotService } from '../../services/copilot.service';
import {
  ChatEntry,
  CopilotActionType,
  CopilotPreview,
  ConversationSummary,
} from '../../core/models/copilot.model';

@Component({
  selector: 'agr-copilot',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="flex gap-4" style="height: calc(100vh - 2rem)">

      <!-- ── History sidebar ─────────────────────────────────────────────── -->
      <div class="w-56 flex-shrink-0 flex flex-col bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <!-- Sidebar header -->
        <div class="px-3 pt-3 pb-2 flex-shrink-0">
          <button
            class="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all"
            (click)="newChat()"
          >
            <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
            </svg>
            New chat
          </button>
        </div>

        <div class="px-3 pb-1 flex-shrink-0">
          <p class="text-xs text-slate-500 uppercase tracking-wide font-semibold">History</p>
        </div>

        <!-- Conversation list -->
        <div class="flex-1 overflow-y-auto px-2 pb-3 space-y-0.5" style="scrollbar-width: thin; scrollbar-color: #334155 transparent;">
          @if (historyLoading()) {
            <div class="flex items-center justify-center py-8">
              <div class="flex gap-1">
                <span class="w-1.5 h-1.5 bg-slate-500 rounded-full animate-bounce" style="animation-delay:0ms"></span>
                <span class="w-1.5 h-1.5 bg-slate-500 rounded-full animate-bounce" style="animation-delay:150ms"></span>
                <span class="w-1.5 h-1.5 bg-slate-500 rounded-full animate-bounce" style="animation-delay:300ms"></span>
              </div>
            </div>
          }
          @if (!historyLoading() && conversations().length === 0) {
            <p class="text-xs text-slate-600 text-center py-6 px-2">No conversations yet</p>
          }
          @for (conv of conversations(); track conv.id) {
            <div
              class="group relative flex items-start gap-2 px-2 py-2 rounded-xl cursor-pointer transition-all"
              [class]="currentConversationId() === conv.id
                ? 'bg-indigo-600/20 border border-indigo-600/40'
                : 'hover:bg-slate-800 border border-transparent'"
              role="button"
              tabindex="0"
              (click)="selectConversation(conv)"
              (keydown.enter)="selectConversation(conv)"
              (keydown.space)="selectConversation(conv)"
            >
              <div class="flex-1 min-w-0">
                <p class="text-xs font-medium truncate"
                  [class]="currentConversationId() === conv.id ? 'text-indigo-300' : 'text-slate-300'">
                  {{ conv.title }}
                </p>
                <p class="text-xs text-slate-600 mt-0.5">{{ relativeTime(conv.updated_at) }}</p>
              </div>
              <!-- Delete button (shows on hover) -->
              <button
                class="opacity-0 group-hover:opacity-100 flex-shrink-0 w-5 h-5 flex items-center justify-center rounded text-slate-500 hover:text-red-400 hover:bg-slate-700 transition-all"
                title="Delete conversation"
                (click)="deleteConversation(conv, $event)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            </div>
          }
        </div>
      </div>

      <!-- ── Chat area ───────────────────────────────────────────────────── -->
      <div class="flex-1 flex flex-col min-w-0">

        <!-- Header -->
        <div class="mb-4 flex-shrink-0">
          <div class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center text-lg">✦</div>
            <div class="flex-1 min-w-0">
              @if (currentConversationId()) {
                <h1 class="text-lg font-semibold text-slate-100 truncate">
                  {{ currentTitle() }}
                </h1>
              } @else {
                <h1 class="text-2xl font-bold text-slate-100">Copilot</h1>
                <p class="text-sm text-slate-400">AI-powered governance assistant — create policies, register agents, and more</p>
              }
            </div>
          </div>
        </div>

        <!-- Messages -->
        <div
          #scrollContainer
          class="flex-1 overflow-y-auto space-y-4 pr-1 mb-4"
          style="scrollbar-width: thin; scrollbar-color: #334155 transparent;"
        >
          <!-- Loading past conversation -->
          @if (loadingConversation()) {
            <div class="flex items-center justify-center h-full">
              <div class="flex gap-1.5">
                <span class="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style="animation-delay:0ms"></span>
                <span class="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style="animation-delay:150ms"></span>
                <span class="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style="animation-delay:300ms"></span>
              </div>
            </div>
          }

          <!-- Welcome state -->
          @if (!loadingConversation() && messages().length === 0) {
            <div class="flex flex-col items-center justify-center h-full text-center px-8">
              <div class="w-16 h-16 rounded-2xl bg-indigo-600/20 border border-indigo-600/30 flex items-center justify-center text-3xl mb-6">✦</div>
              <h2 class="text-xl font-semibold text-slate-100 mb-2">AGR Copilot</h2>
              <p class="text-slate-400 text-sm mb-8 max-w-md">Create Cedar policies, register agents, and manage webhooks using natural language.</p>
              <div class="grid grid-cols-1 gap-2 w-full max-w-lg">
                @for (prompt of starterPrompts; track prompt) {
                  <button
                    class="text-left px-4 py-3 rounded-xl bg-slate-800 border border-slate-700 text-slate-300 text-sm hover:bg-slate-700 hover:border-slate-600 transition-all"
                    (click)="sendStarter(prompt)"
                  >
                    {{ prompt }}
                  </button>
                }
              </div>
            </div>
          }

          <!-- Chat messages -->
          @for (entry of messages(); track entry.timestamp) {
            <div [class]="entry.role === 'user' ? 'flex justify-end' : 'flex justify-start'">
              <div [class]="entry.role === 'user'
                ? 'max-w-[75%] bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-3'
                : 'max-w-[85%] bg-slate-800 border border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3'">

                @if (entry.role === 'assistant') {
                  <div class="flex items-center gap-2 mb-2">
                    <span class="text-indigo-400 text-xs font-semibold uppercase tracking-wide">✦ Copilot</span>
                    @if (entry.action_type && entry.action_type !== 'general' && entry.action_type !== 'error') {
                      <span class="px-2 py-0.5 rounded-full text-xs font-medium" [class]="actionBadgeClass(entry.action_type)">
                        {{ actionLabel(entry.action_type) }}
                      </span>
                    }
                  </div>
                }

                <div class="text-sm leading-relaxed whitespace-pre-wrap"
                  [class]="entry.role === 'user' ? 'text-white' : 'text-slate-200'"
                  [innerHTML]="renderMarkdown(entry.content)">
                </div>

                @if (entry.preview) {
                  <div class="mt-3 p-3 rounded-xl bg-slate-900 border border-slate-600">
                    <div class="text-xs text-slate-400 uppercase tracking-wide mb-2 font-semibold">Preview — {{ entry.preview.resource_type }}</div>
                    @if (entry.preview.cedar_rule) {
                      <pre class="text-xs text-emerald-400 font-mono bg-slate-950 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">{{ entry.preview.cedar_rule }}</pre>
                    }
                    @if (!entry.preview.cedar_rule) {
                      <pre class="text-xs text-slate-300 font-mono bg-slate-950 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">{{ previewJson(entry.preview) }}</pre>
                    }
                    <p class="text-slate-300 text-xs mt-2">{{ entry.preview.confirmation_prompt }}</p>
                    @if (!entry.created_resource) {
                      <div class="flex gap-2 mt-3">
                        <button class="btn-primary text-xs py-1.5 px-3" (click)="confirm(entry)">Confirm</button>
                        <button class="btn-ghost text-xs py-1.5 px-3" (click)="cancel()">Cancel</button>
                      </div>
                    }
                  </div>
                }

                @if (entry.created_resource && entry.action_type === 'confirmed') {
                  <div class="mt-2 inline-flex items-center gap-1.5 text-xs text-emerald-400">
                    <span>✓</span><span>Created successfully</span>
                  </div>
                }

                @if (entry.suggestions && entry.suggestions.length > 0 && !entry.preview) {
                  <div class="flex flex-wrap gap-2 mt-3">
                    @for (s of entry.suggestions; track s) {
                      <button
                        class="px-3 py-1 rounded-full text-xs border border-slate-600 text-slate-300 hover:bg-slate-700 hover:border-slate-500 transition-all"
                        (click)="sendSuggestion(s)"
                      >
                        {{ s }}
                      </button>
                    }
                  </div>
                }

                <div class="text-xs mt-2" [class]="entry.role === 'user' ? 'text-indigo-200' : 'text-slate-500'">
                  {{ formatTime(entry.timestamp) }}
                </div>
              </div>
            </div>
          }

          <!-- Typing indicator -->
          @if (loading()) {
            <div class="flex justify-start">
              <div class="bg-slate-800 border border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3">
                <div class="flex items-center gap-2 mb-2">
                  <span class="text-indigo-400 text-xs font-semibold uppercase tracking-wide">✦ Copilot</span>
                </div>
                <div class="flex gap-1">
                  <span class="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style="animation-delay: 0ms"></span>
                  <span class="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style="animation-delay: 150ms"></span>
                  <span class="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style="animation-delay: 300ms"></span>
                </div>
              </div>
            </div>
          }
        </div>

        <!-- Input bar -->
        <div class="flex-shrink-0">
          <div class="bg-slate-900 border border-slate-700 rounded-2xl p-3 flex items-end gap-3">
            <textarea
              class="flex-1 bg-transparent text-slate-100 text-sm resize-none outline-none placeholder-slate-500 max-h-32 min-h-[2.5rem]"
              placeholder="Ask me to create a policy, register an agent, or anything governance..."
              [(ngModel)]="inputText"
              (keydown)="onKeydown($event)"
              rows="1"
              [disabled]="loading() || loadingConversation()"
            ></textarea>
            <button
              class="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all"
              [class]="canSend() ? 'bg-indigo-600 hover:bg-indigo-500 text-white' : 'bg-slate-800 text-slate-500 cursor-not-allowed'"
              (click)="send()"
              [disabled]="!canSend()"
            >
              <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z"/>
              </svg>
            </button>
          </div>
          <p class="text-center text-xs text-slate-600 mt-2">Copilot can make mistakes. Review all generated policies before confirming.</p>
        </div>
      </div>
    </div>
  `,
})
export class CopilotComponent implements OnInit, AfterViewChecked {
  @ViewChild('scrollContainer') private scrollContainer!: ElementRef<HTMLDivElement>;

  private svc = inject(CopilotService);

  messages = signal<ChatEntry[]>([]);
  conversations = signal<ConversationSummary[]>([]);
  loading = signal(false);
  historyLoading = signal(false);
  loadingConversation = signal(false);
  currentConversationId = signal<string | null>(null);

  inputText = '';
  private shouldScroll = false;

  starterPrompts = [
    '🛡 Create a policy that blocks all production deploys',
    '📋 Show me my current policies',
    '🤖 Register an agent called finance-bot',
    '💡 Show me sample DevOps policies',
  ];

  currentTitle(): string {
    const id = this.currentConversationId();
    if (!id) return 'Copilot';
    return this.conversations().find(c => c.id === id)?.title ?? 'Copilot';
  }

  ngOnInit(): void {
    this.loadConversations();
  }

  loadConversations(): void {
    this.historyLoading.set(true);
    this.svc.listConversations().subscribe({
      next: (convs) => {
        this.conversations.set(convs);
        this.historyLoading.set(false);
      },
      error: () => this.historyLoading.set(false),
    });
  }

  selectConversation(conv: ConversationSummary): void {
    if (this.currentConversationId() === conv.id) return;
    this.loadingConversation.set(true);
    this.currentConversationId.set(conv.id);
    this.messages.set([]);

    this.svc.getConversation(conv.id).subscribe({
      next: (detail) => {
        const entries: ChatEntry[] = detail.messages.map(m => ({
          role: m.role,
          content: m.content,
          action_type: m.action_type as CopilotActionType | undefined,
          preview: m.metadata?.preview,
          created_resource: m.metadata?.created_resource,
          suggestions: m.metadata?.suggestions,
          timestamp: new Date(m.created_at),
        }));
        this.messages.set(entries);
        this.loadingConversation.set(false);
        this.shouldScroll = true;
      },
      error: () => this.loadingConversation.set(false),
    });
  }

  deleteConversation(conv: ConversationSummary, event: Event): void {
    event.stopPropagation();
    this.svc.deleteConversation(conv.id).subscribe({
      next: () => {
        this.conversations.update(cs => cs.filter(c => c.id !== conv.id));
        if (this.currentConversationId() === conv.id) {
          this.currentConversationId.set(null);
          this.messages.set([]);
        }
      },
    });
  }

  newChat(): void {
    this.currentConversationId.set(null);
    this.messages.set([]);
    this.inputText = '';
  }

  canSend(): boolean {
    return this.inputText.trim().length > 0 && !this.loading() && !this.loadingConversation();
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (this.canSend()) this.send();
    }
  }

  send(): void {
    const text = this.inputText.trim();
    if (!text) return;
    this.inputText = '';
    this.sendMessage(text, false);
  }

  sendStarter(prompt: string): void {
    this.sendMessage(prompt.replace(/^[^\w]+ /, ''), false);
  }

  sendSuggestion(text: string): void {
    this.sendMessage(text, false);
  }

  confirm(entry: ChatEntry): void {
    if (!entry.preview) return;
    this.sendMessage(entry.preview.confirmation_prompt, true, entry.preview);
  }

  cancel(): void {
    this.sendMessage('cancel', false);
  }

  private sendMessage(text: string, autoConfirm: boolean, confirmPreview?: CopilotPreview): void {
    this.messages.update(msgs => [...msgs, {
      role: 'user',
      content: text,
      timestamp: new Date(),
    }]);
    this.loading.set(true);
    this.shouldScroll = true;

    this.svc.chat({
      message: text,
      conversation_id: this.currentConversationId(),
      auto_confirm: autoConfirm,
      confirm_preview: confirmPreview,
    }).subscribe({
      next: (res) => {
        // Track conversation id from first response
        if (res.conversation_id) {
          const isNew = !this.currentConversationId();
          this.currentConversationId.set(res.conversation_id);
          if (isNew) this.loadConversations();
          else {
            // Update title in sidebar if it changed
            this.conversations.update(cs =>
              cs.map(c => c.id === res.conversation_id
                ? { ...c, updated_at: new Date().toISOString() }
                : c
              )
            );
          }
        }
        this.messages.update(msgs => [...msgs, {
          role: 'assistant',
          content: res.message,
          action_type: res.action_type,
          preview: res.preview,
          created_resource: res.created_resource,
          suggestions: res.suggestions,
          timestamp: new Date(),
        }]);
        this.loading.set(false);
        this.shouldScroll = true;
      },
      error: (err) => {
        const errMsg = err?.error?.detail ?? 'Something went wrong. Please try again.';
        this.messages.update(msgs => [...msgs, {
          role: 'assistant',
          content: `Error: ${errMsg}`,
          action_type: 'error' as CopilotActionType,
          timestamp: new Date(),
        }]);
        this.loading.set(false);
      },
    });
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll) {
      this.scrollToBottom();
      this.shouldScroll = false;
    }
  }

  private scrollToBottom(): void {
    try {
      const el = this.scrollContainer?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    } catch {}
  }

  renderMarkdown(text: string): string {
    return text
      .replace(/```([\s\S]*?)```/g, '<pre class="text-xs text-emerald-400 font-mono bg-slate-950 rounded-lg p-3 overflow-x-auto mt-2 mb-2 whitespace-pre-wrap">$1</pre>')
      .replace(/`([^`]+)`/g, '<code class="text-indigo-300 bg-slate-900 px-1 rounded text-xs font-mono">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong class="text-slate-100 font-semibold">$1</strong>')
      .replace(/\n/g, '<br>');
  }

  previewJson(preview: CopilotPreview): string {
    return JSON.stringify(preview.data, null, 2);
  }

  formatTime(d: Date): string {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  relativeTime(iso: string): string {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  }

  actionLabel(type: CopilotActionType): string {
    const labels: Partial<Record<CopilotActionType, string>> = {
      create_policy: 'Policy', list_policies: 'Policies',
      register_agent: 'Agent', list_agents: 'Agents',
      create_webhook: 'Webhook', list_webhooks: 'Webhooks',
      explain: 'Explain', sample: 'Samples',
      confirmed: 'Created ✓', cancelled: 'Cancelled', error: 'Error',
    };
    return labels[type] ?? type;
  }

  actionBadgeClass(type: CopilotActionType): string {
    if (type === 'confirmed') return 'bg-emerald-900/50 text-emerald-400 border border-emerald-800';
    if (type === 'error' || type === 'cancelled') return 'bg-red-900/50 text-red-400 border border-red-800';
    if (type.startsWith('create') || type === 'register_agent') return 'bg-indigo-900/50 text-indigo-400 border border-indigo-800';
    return 'bg-slate-700 text-slate-300 border border-slate-600';
  }
}
