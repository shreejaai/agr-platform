import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Policy, PolicyCreate, PolicyUpdate } from '../core/models/policy.model';

export interface PolicyListParams {
  active?: boolean;
  limit?: number;
}

@Injectable({ providedIn: 'root' })
export class PolicyService {
  private http = inject(HttpClient);

  list(params: PolicyListParams = {}): Observable<Policy[]> {
    let p = new HttpParams();
    if (params.active !== undefined) p = p.set('active', String(params.active));
    if (params.limit != null) p = p.set('limit', String(params.limit));
    return this.http.get<Policy[]>('/v1/policies', { params: p });
  }

  get(id: string): Observable<Policy> {
    return this.http.get<Policy>(`/v1/policies/${id}`);
  }

  create(body: PolicyCreate): Observable<Policy> {
    return this.http.post<Policy>('/v1/policies', body);
  }

  update(id: string, body: PolicyUpdate): Observable<Policy> {
    return this.http.patch<Policy>(`/v1/policies/${id}`, body);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`/v1/policies/${id}`);
  }
}
