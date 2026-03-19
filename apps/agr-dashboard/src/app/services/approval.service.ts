import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Approval, ApprovalDecideRequest } from '../core/models/approval.model';

@Injectable({ providedIn: 'root' })
export class ApprovalService {
  private http = inject(HttpClient);

  list(status?: string): Observable<Approval[]> {
    const params = status ? new HttpParams().set('status', status) : undefined;
    return this.http.get<Approval[]>('/v1/approvals', { params });
  }

  get(id: string): Observable<Approval> {
    return this.http.get<Approval>(`/v1/approvals/${id}`);
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
}
