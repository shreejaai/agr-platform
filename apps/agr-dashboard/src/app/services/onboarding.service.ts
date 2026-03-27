import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'agr_onboarding_dismissed';

@Injectable({ providedIn: 'root' })
export class OnboardingService {
  private readonly dismissedState = signal(localStorage.getItem(STORAGE_KEY) === 'true');

  dismissed(): boolean {
    return this.dismissedState();
  }

  dismiss(): void {
    localStorage.setItem(STORAGE_KEY, 'true');
    this.dismissedState.set(true);
  }

  resume(): void {
    localStorage.removeItem(STORAGE_KEY);
    this.dismissedState.set(false);
  }
}
