import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'agr_api_key';

@Injectable({ providedIn: 'root' })
export class ApiKeyService {
  private _key = signal<string | null>(sessionStorage.getItem(STORAGE_KEY));

  getKey(): string | null {
    return this._key();
  }

  hasKey(): boolean {
    return !!this._key();
  }

  isSessionDerived(): boolean {
    return this._key()?.startsWith('agr_usr_') ?? false;
  }

  getAuthMode(): 'session' | 'api_key' {
    return this.isSessionDerived() ? 'session' : 'api_key';
  }

  setKey(key: string): void {
    sessionStorage.setItem(STORAGE_KEY, key);
    this._key.set(key);
  }

  clearKey(): void {
    sessionStorage.removeItem(STORAGE_KEY);
    this._key.set(null);
  }
}
