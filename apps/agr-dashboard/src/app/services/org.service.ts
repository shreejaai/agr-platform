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
  eval_warning_threshold_pct: number;
  eval_soft_limit_enabled: boolean;
  eval_week_start: string | null;
  role: 'admin' | 'operator' | 'viewer';
  auth_mode: 'api_key' | 'sso_session';
  auth_expires_at: string | null;
  sso_enabled: boolean;
  sso_provider: string | null;
  created_at: string;
}

export interface AgentUsageSummary {
  agent_id: string;
  total_evaluations: number;
  share_pct: number;
  last_evaluated_at: string | null;
}

export interface UsageSummary {
  org_id: string;
  total_evaluations: number;
  eval_limit: number;
  eval_warning_threshold_pct: number;
  eval_soft_limit_enabled: boolean;
  usage_pct: number;
  quota_state: 'ok' | 'warning' | 'exceeded';
  warning_message: string | null;
  per_agent: AgentUsageSummary[];
}

export interface SsoSettings {
  enabled: boolean;
  provider: string | null;
  metadata_url: string | null;
  metadata_xml: string | null;
  entity_id: string | null;
  domains: string[];
  default_role: 'admin' | 'operator' | 'viewer';
  auto_join: boolean;
}

@Injectable({ providedIn: 'root' })
export class OrgService {
  private http = inject(HttpClient);

  getMe(): Observable<OrgMe> {
    return this.http.get<OrgMe>('/v1/org/me');
  }

  getUsage(): Observable<UsageSummary> {
    return this.http.get<UsageSummary>('/v1/usage');
  }

  getSso(): Observable<SsoSettings> {
    return this.http.get<SsoSettings>('/v1/org/sso');
  }

  updateSso(body: Partial<SsoSettings>): Observable<SsoSettings> {
    return this.http.put<SsoSettings>('/v1/org/sso', body);
  }
}
