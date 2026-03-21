import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Policy, PolicyCreate, PolicyUpdate } from '../core/models/policy.model';

export interface PolicyListParams {
  active?: boolean;
  limit?: number;
}

export interface PolicyImportItem {
  name: string;
  level: 'org' | 'project' | 'agent';
  cedar_rule: string;
  active?: boolean;
  agent_id?: string | null;
  project_id?: string | null;
}

export interface PolicyImportRequest {
  policies: PolicyImportItem[];
  dry_run?: boolean;
  overwrite?: boolean;
}

export interface PolicyImportResult {
  name: string;
  status: 'created' | 'updated' | 'skipped' | 'error';
  policy_id?: string | null;
  error?: string | null;
}

export interface PolicyImportResponse {
  dry_run: boolean;
  total: number;
  created: number;
  updated: number;
  skipped: number;
  errors: number;
  results: PolicyImportResult[];
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

  importPolicies(body: PolicyImportRequest): Observable<PolicyImportResponse> {
    return this.http.post<PolicyImportResponse>('/v1/policies/import', body);
  }

  exportPolicies(activeOnly = false): Observable<PolicyImportItem[]> {
    let p = new HttpParams();
    if (activeOnly) p = p.set('active_only', 'true');
    return this.http.get<PolicyImportItem[]>('/v1/policies/export', { params: p });
  }
}
