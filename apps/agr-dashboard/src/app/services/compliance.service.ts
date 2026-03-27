import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface ComplianceExportParams {
  period_days?: number;
  format?: 'json' | 'csv' | 'pdf';
}

@Injectable({ providedIn: 'root' })
export class ComplianceService {
  private http = inject(HttpClient);

  exportReport(params: ComplianceExportParams = {}): Observable<Blob> {
    let httpParams = new HttpParams();
    if (params.period_days != null) httpParams = httpParams.set('period_days', String(params.period_days));
    httpParams = httpParams.set('format', params.format ?? 'json');
    return this.http.get('/v1/compliance/export', {
      params: httpParams,
      responseType: 'blob',
      observe: 'body',
    });
  }
}
