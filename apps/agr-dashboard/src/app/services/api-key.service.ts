import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'agr_api_key';

@Injectable({ providedIn: 'root' })
export class ApiKeyService {
  private _key = signal<string | null>(localStorage.getItem(STORAGE_KEY));

  getKey(): string | null {
    return this._key();
  }

  hasKey(): boolean {
    return !!this._key();
  }

  setKey(key: string): void {
    localStorage.setItem(STORAGE_KEY, key);
    this._key.set(key);
  }

  clearKey(): void {
    localStorage.removeItem(STORAGE_KEY);
    this._key.set(null);
  }
}
