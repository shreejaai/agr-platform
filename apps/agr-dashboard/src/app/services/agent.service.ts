import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Agent, AgentRegisterRequest } from '../core/models/agent.model';

@Injectable({ providedIn: 'root' })
export class AgentService {
  private http = inject(HttpClient);

  list(): Observable<Agent[]> {
    return this.http.get<Agent[]>('/v1/agents');
  }

  get(id: string): Observable<Agent> {
    return this.http.get<Agent>(`/v1/agents/${id}`);
  }

  register(body: AgentRegisterRequest): Observable<Agent> {
    return this.http.post<Agent>('/v1/agents/register', body);
  }
}
