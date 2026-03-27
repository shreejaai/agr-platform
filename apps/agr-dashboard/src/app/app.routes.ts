import { Routes } from '@angular/router';
import { authGuard } from './core/auth/auth.guard';
import { apiKeyGuard } from './core/auth/api-key.guard';
import { publicGuard } from './core/auth/public.guard';

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [publicGuard],
    loadComponent: () =>
      import('./pages/login/login.component').then((m) => m.LoginComponent),
  },
  {
    path: '',
    loadComponent: () =>
      import('./layout/shell/shell.component').then((m) => m.ShellComponent),
    canActivate: [authGuard],
    children: [
      { path: '', redirectTo: 'home', pathMatch: 'full' },
      {
        path: 'home',
        loadComponent: () =>
          import('./pages/home/home.component').then((m) => m.HomeComponent),
      },
      {
        path: 'approvals',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/approvals/approvals.component').then((m) => m.ApprovalsComponent),
      },
      {
        path: 'policies',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/policies/policies.component').then((m) => m.PoliciesComponent),
      },
      {
        path: 'audit',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/audit/audit.component').then((m) => m.AuditComponent),
      },
      {
        path: 'agents',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/agents/agents.component').then((m) => m.AgentsComponent),
      },
      {
        path: 'webhooks',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/webhooks/webhooks.component').then((m) => m.WebhooksComponent),
      },
      {
        path: 'copilot',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/copilot/copilot.component').then((m) => m.CopilotComponent),
      },
      {
        path: 'simulator',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/policy-simulator/policy-simulator.component').then(
            (m) => m.PolicySimulatorComponent
          ),
      },
      {
        path: 'team',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/team/team.component').then((m) => m.TeamComponent),
      },
      {
        path: 'settings',
        loadComponent: () =>
          import('./pages/settings/settings.component').then((m) => m.SettingsComponent),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
