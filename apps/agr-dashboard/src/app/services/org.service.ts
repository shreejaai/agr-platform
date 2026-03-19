import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface OrgMe {
  id: string;
  name: string;
  slug: string | null;
  plan: string;
  eval_count: number;
  eval_limit: number;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class OrgService {
  private http = inject(HttpClient);

  getMe(): Observable<OrgMe> {
    return this.http.get<OrgMe>('/v1/org/me');
  }
}
