import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Agent, AgentRegister, AgentRegisterRequest, AgentUpdate } from '../core/models/agent.model';

export interface AgentListParams {
  limit?: number;
}

@Injectable({ providedIn: 'root' })
export class AgentService {
  private http = inject(HttpClient);

  list(params: AgentListParams = {}): Observable<Agent[]> {
    let p = new HttpParams();
    if (params.limit != null) p = p.set('limit', String(params.limit));
    return this.http.get<Agent[]>('/v1/agents', { params: p });
  }

  get(id: string): Observable<Agent> {
    return this.http.get<Agent>(`/v1/agents/${id}`);
  }

  /** Convert friendly AgentRegister form into the API's AgentRegisterRequest. */
  register(form: AgentRegister): Observable<Agent> {
    const body: AgentRegisterRequest = {
      agent_id: form.agent_id,
      metadata: {
        name: form.name,
        ...(form.description?.trim() ? { description: form.description.trim() } : {}),
        ...(form.framework?.trim() ? { framework: form.framework.trim() } : {}),
      },
    };
    return this.http.post<Agent>('/v1/agents/register', body);
  }

  update(id: string, body: AgentUpdate): Observable<Agent> {
    return this.http.patch<Agent>(`/v1/agents/${id}`, body);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`/v1/agents/${id}`, { responseType: 'text' as 'json' });
  }
}
