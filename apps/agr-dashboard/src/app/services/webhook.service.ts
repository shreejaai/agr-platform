import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Webhook, WebhookCreate } from '../core/models/webhook.model';

@Injectable({ providedIn: 'root' })
export class WebhookService {
  private http = inject(HttpClient);

  list(): Observable<Webhook[]> {
    return this.http.get<Webhook[]>('/v1/webhooks');
  }

  get(id: string): Observable<Webhook> {
    return this.http.get<Webhook>(`/v1/webhooks/${id}`);
  }

  create(body: WebhookCreate): Observable<Webhook> {
    return this.http.post<Webhook>('/v1/webhooks', body);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`/v1/webhooks/${id}`);
  }
}
