import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { AuditEvent, AuditFilter } from '../core/models/audit-event.model';

/** Result of a cursor-paginated audit query (W4.2). */
export interface AuditPage {
  events: AuditEvent[];
  /** Cursor value to pass back as `after` to fetch the next page, or null when no more. */
  nextCursor: string | null;
}

export interface AuditVerifyResult {
  valid: boolean;
  total: number;
  first_invalid_sequence: number | null;
}

export interface AuditSearchParams extends AuditFilter {
  action?: string;
  decision?: string;
}

export interface AuditExportParams {
  event_type?: string;
  agent_id?: string;
  action?: string;
  decision?: string;
  start_date?: string;
  end_date?: string;
  format?: 'json' | 'csv';
}

@Injectable({ providedIn: 'root' })
export class AuditService {
  private http = inject(HttpClient);

  list(filter: AuditFilter = {}): Observable<AuditEvent[]> {
    let params = new HttpParams();
    if (filter.event_type) params = params.set('event_type', filter.event_type);
    if (filter.agent_id) params = params.set('agent_id', filter.agent_id);
    if (filter.policy_id) params = params.set('policy_id', filter.policy_id);
    // Map convenience 'date' to start_date; honour explicit start/end if provided
    if (filter.date) params = params.set('start_date', filter.date);
    if (filter.start_date && !filter.date) params = params.set('start_date', filter.start_date);
    if (filter.end_date) params = params.set('end_date', filter.end_date);
    if (filter.limit != null) params = params.set('limit', String(filter.limit));
    if (filter.offset != null) params = params.set('offset', String(filter.offset));
    return this.http.get<AuditEvent[]>('/v1/audit', { params });
  }

  search(p: AuditSearchParams): Observable<AuditEvent[]> {
    let params = new HttpParams();
    if (p.event_type) params = params.set('event_type', p.event_type);
    if (p.agent_id) params = params.set('agent_id', p.agent_id);
    if (p.policy_id) params = params.set('policy_id', p.policy_id);
    if (p.action) params = params.set('action', p.action);
    if (p.decision) params = params.set('decision', p.decision);
    if (p.start_date) params = params.set('start_date', p.start_date);
    if (p.end_date) params = params.set('end_date', p.end_date);
    if (p.limit != null) params = params.set('limit', String(p.limit));
    if (p.offset != null) params = params.set('offset', String(p.offset));
    return this.http.get<AuditEvent[]>('/v1/audit', { params });
  }

  /**
   * Cursor-paginated list (W4.2). When `after` is provided the API returns
   * events with sequence_num strictly less than that cursor and sets the
   * `X-AGR-Next-Cursor` response header when more pages may exist.
   */
  searchWithCursor(p: AuditSearchParams & { after?: string | null }): Observable<AuditPage> {
    let params = new HttpParams();
    if (p.event_type) params = params.set('event_type', p.event_type);
    if (p.agent_id) params = params.set('agent_id', p.agent_id);
    if (p.policy_id) params = params.set('policy_id', p.policy_id);
    if (p.action) params = params.set('action', p.action);
    if (p.decision) params = params.set('decision', p.decision);
    if (p.start_date) params = params.set('start_date', p.start_date);
    if (p.end_date) params = params.set('end_date', p.end_date);
    if (p.limit != null) params = params.set('limit', String(p.limit));
    if (p.after) params = params.set('after', p.after);
    return this.http
      .get<AuditEvent[]>('/v1/audit', { params, observe: 'response' })
      .pipe(
        map((resp) => ({
          events: resp.body ?? [],
          nextCursor: resp.headers.get('X-AGR-Next-Cursor'),
        })),
      );
  }

  verify(): Observable<AuditVerifyResult> {
    return this.http.get<AuditVerifyResult>('/v1/audit/verify');
  }

  export(p: AuditExportParams): Observable<Blob> {
    return this.http.post('/v1/audit/export', { ...p, format: p.format ?? 'json' }, { responseType: 'blob' });
  }
}
