import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Approval, ApprovalDecideRequest, ApprovalStep } from '../core/models/approval.model';

export interface ApprovalListParams {
  status?: string;
  limit?: number;
  offset?: number;
}

@Injectable({ providedIn: 'root' })
export class ApprovalService {
  private http = inject(HttpClient);

  list(params: ApprovalListParams = {}): Observable<Approval[]> {
    let p = new HttpParams();
    if (params.status) p = p.set('status', params.status);
    if (params.limit != null) p = p.set('limit', String(params.limit));
    if (params.offset != null) p = p.set('offset', String(params.offset));
    return this.http.get<Approval[]>('/v1/approvals', { params: p });
  }

  get(id: string): Observable<Approval> {
    return this.http.get<Approval>(`/v1/approvals/${id}`);
  }

  listSteps(id: string): Observable<ApprovalStep[]> {
    return this.http.get<ApprovalStep[]>(`/v1/approvals/${id}/steps`);
  }

  decide(id: string, body: ApprovalDecideRequest): Observable<Approval> {
    return this.http.post<Approval>(`/v1/approvals/${id}/decide`, body);
  }

  approve(id: string, reason = ''): Observable<Approval> {
    return this.decide(id, { decision: 'approved', decided_by: 'dashboard', reason });
  }

  reject(id: string, reason = ''): Observable<Approval> {
    return this.decide(id, { decision: 'rejected', decided_by: 'dashboard', reason });
  }

  escalate(id: string, approver_email: string): Observable<Approval> {
    return this.http.post<Approval>(`/v1/approvals/${id}/escalate`, { approver_email });
  }
}
