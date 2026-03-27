import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  Policy,
  PolicyCreate,
  PolicyUpdate,
  PolicyImportItem,
  PolicyImportRequest,
  PolicyImportResponse,
} from '../core/models/policy.model';

export interface PolicyListParams {
  active?: boolean;
  limit?: number;
}

export interface SimulateRequest {
  agent_id: string;
  action: string;
  resource: string;
  context?: Record<string, unknown>;
}

export interface DecisionTrace {
  policy_source: string | null;
  cedar_decision: string | null;
  risk_override: boolean;
  fallback_used: boolean;
  fallback_reason: string | null;
}

export interface SimulateResponse {
  decision: 'ALLOW' | 'DENY' | 'APPROVAL_REQUIRED';
  reason: string;
  risk_score: number;
  risk_level: string;
  decision_trace: DecisionTrace;
}

export interface SimulateResult {
  decision: 'ALLOW' | 'DENY' | 'APPROVAL_REQUIRED';
  reason: string;
  policy_id: string | null;
  risk_score: number | null;
  risk_level: string | null;
  risk_factors: Record<string, number> | null;
  decision_trace: DecisionTrace | null;
}

export interface PolicyVersion {
  version: number;
  cedar_rule: string;
  name: string;
  updated_at: string;
  updated_by: string | null;
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
    return this.http.delete<void>(`/v1/policies/${id}`, { responseType: 'text' as 'json' });
  }

  importPolicies(body: PolicyImportRequest): Observable<PolicyImportResponse> {
    return this.http.post<PolicyImportResponse>('/v1/policies/import', body);
  }

  exportPolicies(activeOnly = false): Observable<PolicyImportItem[]> {
    let p = new HttpParams();
    if (activeOnly) p = p.set('active_only', 'true');
    return this.http.get<PolicyImportItem[]>('/v1/policies/export', { params: p });
  }

  simulate(req: SimulateRequest): Observable<SimulateResponse> {
    return this.http.post<SimulateResponse>('/v1/policies/simulate', req);
  }

  getVersions(policyId: string): Observable<PolicyVersion[]> {
    return this.http.get<PolicyVersion[]>(`/v1/policies/${policyId}/versions`);
  }

  rollback(policyId: string, version: number): Observable<Policy> {
    return this.http.post<Policy>(`/v1/policies/${policyId}/rollback`, { version });
  }

  simulatePolicy(payload: {
    agent_id: string;
    action: string;
    resource: string;
    context: Record<string, unknown>;
  }): Observable<SimulateResult> {
    return this.http.post<SimulateResult>('/v1/policies/simulate', payload);
  }
}
