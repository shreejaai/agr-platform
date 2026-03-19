import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Policy, PolicyCreate, PolicyUpdate } from '../core/models/policy.model';

@Injectable({ providedIn: 'root' })
export class PolicyService {
  private http = inject(HttpClient);

  list(active?: boolean): Observable<Policy[]> {
    const params =
      active !== undefined ? new HttpParams().set('active', String(active)) : undefined;
    return this.http.get<Policy[]>('/v1/policies', { params });
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
