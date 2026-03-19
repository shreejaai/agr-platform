import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AuditEvent, AuditFilter } from '../core/models/audit-event.model';

@Injectable({ providedIn: 'root' })
export class AuditService {
  private http = inject(HttpClient);

  list(filter: AuditFilter = {}): Observable<AuditEvent[]> {
    let params = new HttpParams();
    if (filter.event_type) params = params.set('event_type', filter.event_type);
    if (filter.agent_id) params = params.set('agent_id', filter.agent_id);
    // Map convenience 'date' to start_date; honour explicit start/end if provided
    if (filter.date) params = params.set('start_date', filter.date);
    if (filter.start_date && !filter.date) params = params.set('start_date', filter.start_date);
    if (filter.end_date) params = params.set('end_date', filter.end_date);
    if (filter.limit != null) params = params.set('limit', String(filter.limit));
    if (filter.offset != null) params = params.set('offset', String(filter.offset));
    return this.http.get<AuditEvent[]>('/v1/audit', { params });
  }
}
