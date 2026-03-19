import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Webhook, WebhookCreate } from '../core/models/webhook.model';

export interface WebhookListParams {
  limit?: number;
}

@Injectable({ providedIn: 'root' })
export class WebhookService {
  private http = inject(HttpClient);

  list(params: WebhookListParams = {}): Observable<Webhook[]> {
    let p = new HttpParams();
    if (params.limit != null) p = p.set('limit', String(params.limit));
    return this.http.get<Webhook[]>('/v1/webhooks', { params: p });
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
