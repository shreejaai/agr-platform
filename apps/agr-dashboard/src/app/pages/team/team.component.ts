import {
  Component,
  OnInit,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  MemberService,
  OrgMember,
} from '../../services/member.service';

@Component({
  selector: 'agr-team',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './team.component.html',
})
export class TeamComponent implements OnInit {
  private memberService = inject(MemberService);

  members = signal<OrgMember[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);

  // Invite form
  inviteEmail = signal('');
  inviteRole = signal<'admin' | 'operator' | 'viewer'>('viewer');
  inviting = signal(false);
  inviteError = signal<string | null>(null);
  inviteSuccess = signal(false);

  ngOnInit(): void {
    this.loadMembers();
  }

  loadMembers(): void {
    this.loading.set(true);
    this.memberService.listMembers().subscribe({
      next: (data) => {
        this.members.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Failed to load team members.');
        this.loading.set(false);
      },
    });
  }

  invite(): void {
    const email = this.inviteEmail().trim();
    if (!email) return;

    this.inviting.set(true);
    this.inviteError.set(null);
    this.inviteSuccess.set(false);

    this.memberService.inviteMember({ email, role: this.inviteRole() }).subscribe({
      next: (member) => {
        this.members.update((list) => [...list, member]);
        this.inviteEmail.set('');
        this.inviteRole.set('viewer');
        this.inviting.set(false);
        this.inviteSuccess.set(true);
        setTimeout(() => this.inviteSuccess.set(false), 3000);
      },
      error: (err: { error?: { detail?: { message?: string } | string } }) => {
        const detail = err?.error?.detail;
        const msg = typeof detail === 'object' ? detail?.message : String(detail ?? 'Invite failed.');
        this.inviteError.set(msg ?? 'Invite failed.');
        this.inviting.set(false);
      },
    });
  }

  updateRole(member: OrgMember, role: 'admin' | 'operator' | 'viewer'): void {
    this.memberService.updateMemberRole(member.id, { role }).subscribe({
      next: (updated) => {
        this.members.update((list) =>
          list.map((m) => (m.id === updated.id ? updated : m))
        );
      },
      error: () => {
        this.error.set('Failed to update role.');
      },
    });
  }

  revoke(member: OrgMember): void {
    if (!confirm(`Revoke access for ${member.email}?`)) return;
    this.memberService.revokeMember(member.id).subscribe({
      next: () => {
        this.members.update((list) =>
          list.map((m) => (m.id === member.id ? { ...m, status: 'revoked' as const } : m))
        );
      },
      error: () => {
        this.error.set('Failed to revoke access.');
      },
    });
  }

  statusBadgeClass(status: string): string {
    switch (status) {
      case 'active':  return 'bg-green-900 text-green-300';
      case 'invited': return 'bg-yellow-900 text-yellow-300';
      case 'revoked': return 'bg-red-900 text-red-300';
      default:        return 'bg-gray-700 text-gray-400';
    }
  }

  roleBadgeClass(role: string): string {
    switch (role) {
      case 'admin':    return 'bg-indigo-900 text-indigo-300';
      case 'operator': return 'bg-blue-900 text-blue-300';
      default:         return 'bg-gray-700 text-gray-400';
    }
  }

  activeMembers(): OrgMember[] {
    return this.members().filter((m) => m.status !== 'revoked');
  }

  revokedMembers(): OrgMember[] {
    return this.members().filter((m) => m.status === 'revoked');
  }
}
