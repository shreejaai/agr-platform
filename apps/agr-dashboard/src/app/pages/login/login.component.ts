import { Component, inject, ChangeDetectionStrategy, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ClerkService } from '../../core/auth/clerk.service';

@Component({
  selector: 'agr-login',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div class="w-full max-w-md">
        <!-- Brand -->
        <div class="text-center mb-8">
          <h1 class="text-3xl font-bold text-indigo-400 tracking-tight">AGR</h1>
          <p class="text-slate-400 mt-1 text-sm">Agentic Governance Runtime</p>
        </div>

        <!-- Card -->
        <div class="card">
          <h2 class="text-lg font-semibold text-slate-100 mb-2">Sign in to your dashboard</h2>
          <p class="text-sm text-slate-400 mb-6">
            Use your organisation account to access policy management and approval workflows.
          </p>

          @if (error()) {
            <div class="mb-4 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20">
              <p class="text-sm text-red-400">{{ error() }}</p>
            </div>
          }

          <button
            (click)="signIn()"
            [disabled]="loading()"
            class="btn-primary w-full flex items-center justify-center gap-2"
          >
            @if (loading()) {
              <span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
              Signing in…
            } @else {
              Sign in with Clerk
            }
          </button>

          <p class="text-xs text-slate-500 text-center mt-4">
            Powered by Clerk for secure authentication
          </p>
        </div>
      </div>
    </div>
  `,
})
export class LoginComponent {
  private clerk = inject(ClerkService);
  private router = inject(Router);

  readonly loading = signal(false);
  readonly error = signal('');

  async signIn(): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    try {
      await this.clerk.signIn();
      await this.router.navigate(['/home']);
    } catch (e: unknown) {
      this.error.set(e instanceof Error ? e.message : 'Sign-in failed. Please try again.');
    } finally {
      this.loading.set(false);
    }
  }
}
