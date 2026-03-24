import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  ConversationDetail,
  ConversationSummary,
  CopilotRequest,
  CopilotResponse,
} from '../core/models/copilot.model';

@Injectable({ providedIn: 'root' })
export class CopilotService {
  private http = inject(HttpClient);

  chat(req: CopilotRequest): Observable<CopilotResponse> {
    return this.http.post<CopilotResponse>('/v1/copilot/chat', req);
  }

  listConversations(): Observable<ConversationSummary[]> {
    return this.http.get<ConversationSummary[]>('/v1/copilot/conversations');
  }

  getConversation(id: string): Observable<ConversationDetail> {
    return this.http.get<ConversationDetail>(`/v1/copilot/conversations/${id}`);
  }

  deleteConversation(id: string): Observable<void> {
    return this.http.delete<void>(`/v1/copilot/conversations/${id}`, { responseType: 'text' as 'json' });
  }
}
