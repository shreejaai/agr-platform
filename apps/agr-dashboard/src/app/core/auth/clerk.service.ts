import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { Clerk } from '@clerk/clerk-js';
import { environment } from '../../../environments/environment';
import { ApiKeyService } from '../../services/api-key.service';

export interface ClerkUser {
  id: string;
  email: string;
  fullName: string;
}

@Injectable({ providedIn: 'root' })
export class ClerkService {
  private clerk: any = null;
  private http = inject(HttpClient);
  private apiKeySvc = inject(ApiKeyService);

  readonly isLoaded = signal(false);
  readonly user = signal<ClerkUser | null>(null);

  async init(): Promise<void> {
    const key = environment.clerkPublishableKey;
    if (!key || key.includes('REPLACE_WITH')) {
      console.warn('ClerkService: publishableKey not configured — auth disabled.');
      return;
    }
    try {
      this.clerk = new (Clerk as any)(key);
      await this.clerk.load();
      this.isLoaded.set(true);
      this._syncUser();
      // Auto-fetch AGR API key from Clerk session (if not already stored)
      if (this.clerk?.user && !this.apiKeySvc.hasKey()) {
        await this._fetchApiKey();
      }
    } catch (err) {
      console.error('ClerkService: failed to initialise Clerk', err);
    }
  }

  private async _fetchApiKey(): Promise<void> {
    try {
      const token: string = await this.clerk.session.getToken();
      const res = await firstValueFrom(
        this.http.get<{ api_key: string }>('/v1/clerk/api-key', {
          headers: { Authorization: `Bearer ${token}` },
        })
      );
      if (res?.api_key) {
        this.apiKeySvc.setKey(res.api_key);
      }
    } catch {
      // Silently ignore — user can paste key manually in Settings
    }
  }

  private _syncUser(): void {
    const u = this.clerk.user;
    this.user.set(
      u
        ? {
            id: u.id,
            email: u.primaryEmailAddress?.emailAddress ?? '',
            fullName: [u.firstName, u.lastName].filter(Boolean).join(' ') || 'User',
          }
        : null,
    );
  }

  isSignedIn(): boolean {
    return !!this.clerk?.user;
  }

  async signIn(): Promise<void> {
    await this.clerk?.redirectToSignIn({ afterSignInUrl: '/' });
  }

  async signOut(): Promise<void> {
    await this.clerk?.signOut();
    this.user.set(null);
  }
}
