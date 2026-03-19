import { Injectable, signal } from '@angular/core';
import Clerk from '@clerk/clerk-js';
import { environment } from '../../../environments/environment';

export interface ClerkUser {
  id: string;
  email: string;
  fullName: string;
}

@Injectable({ providedIn: 'root' })
export class ClerkService {
  private clerk = new Clerk(environment.clerkPublishableKey);

  readonly isLoaded = signal(false);
  readonly user = signal<ClerkUser | null>(null);

  async init(): Promise<void> {
    await this.clerk.load();
    this.isLoaded.set(true);
    this._syncUser();
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
    return !!this.clerk.user;
  }

  async signIn(): Promise<void> {
    await this.clerk.redirectToSignIn();
  }

  async signOut(): Promise<void> {
    await this.clerk.signOut();
    this.user.set(null);
  }
}
