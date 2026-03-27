import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface OrgMember {
  id: string;
  org_id: string;
  email: string;
  role: 'admin' | 'operator' | 'viewer';
  status: 'invited' | 'active' | 'revoked';
  invited_by: string | null;
  joined_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InviteMemberRequest {
  email: string;
  role: 'admin' | 'operator' | 'viewer';
}

export interface UpdateMemberRequest {
  role: 'admin' | 'operator' | 'viewer';
}

@Injectable({ providedIn: 'root' })
export class MemberService {
  private http = inject(HttpClient);

  listMembers(): Observable<OrgMember[]> {
    return this.http.get<OrgMember[]>('/v1/org/members');
  }

  inviteMember(req: InviteMemberRequest): Observable<OrgMember> {
    return this.http.post<OrgMember>('/v1/org/members/invite', req);
  }

  updateMemberRole(id: string, req: UpdateMemberRequest): Observable<OrgMember> {
    return this.http.patch<OrgMember>(`/v1/org/members/${id}`, req);
  }

  revokeMember(id: string): Observable<void> {
    return this.http.delete<void>(`/v1/org/members/${id}`);
  }
}
