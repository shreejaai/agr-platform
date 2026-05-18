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

export type FetchKeyResult =
  | { ok: true }
  | {
      ok: false;
      reason:
        | 'not_signed_in'
        | 'clerk_not_configured'
        | 'org_not_found'
        | 'access_denied'
        | 'ambiguous_org_mapping'
        | 'error';
    };

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
        await this.fetchApiKey();
      }
    } catch (err) {
      console.error('ClerkService: failed to initialise Clerk', err);
    }
  }

  /**
   * Fetch the AGR API key from the backend using the current Clerk session.
   *
   * Retries up to 3 times with a 2-second delay to handle the race between
  /**
   * Exchange a Clerk session for an AGR API key.
   *
   * The backend `/v1/clerk/api-key` endpoint auto-provisions the org row JIT
   * for any verified Clerk user (W2.5), so we no longer need to poll while
   * waiting for the Clerk webhook to land. Returns a result object so callers
   * can surface failures to the user.
   */
  async fetchApiKey(): Promise<FetchKeyResult> {
    if (!this.clerk?.session) {
      return { ok: false, reason: 'not_signed_in' };
    }

    try {
      const token: string = await this.clerk.session.getToken();
      const res = await firstValueFrom(
        this.http.get<{ api_key: string }>('/v1/clerk/api-key', {
          headers: { Authorization: `Bearer ${token}` },
        })
      );
      if (res?.api_key) {
        if (res.api_key.startsWith('agr_sk_')) {
          console.warn(
            'Warning: SSO exchange returned a raw API key. Configure CLERK_SESSION_MODE=session on the backend.',
          );
        }
        this.apiKeySvc.setKey(res.api_key);
        return { ok: true };
      }
      return { ok: false, reason: 'error' };
    } catch (err: any) {
      const status: number = err?.status ?? 0;

      if (status === 503) {
        return { ok: false, reason: 'clerk_not_configured' };
      }
      if (status === 404) {
        // Backend now JIT-provisions on every call, so 404 is a real "not
        // mapped" condition (e.g. session token belongs to a deleted org).
        return { ok: false, reason: 'org_not_found' };
      }
      if (status === 403) {
        return { ok: false, reason: 'access_denied' };
      }
      if (status === 409) {
        return { ok: false, reason: 'ambiguous_org_mapping' };
      }

      console.warn('ClerkService: fetchApiKey failed', err);
      return { ok: false, reason: 'error' };
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
