import { of } from 'rxjs';
import { TestBed } from '@angular/core/testing';

import { ApiKeyService } from '../../services/api-key.service';
import { ComplianceService } from '../../services/compliance.service';
import { OrgService } from '../../services/org.service';
import { ClerkService } from '../../core/auth/clerk.service';
import { SettingsComponent } from './settings.component';

describe('SettingsComponent', () => {
  let component: SettingsComponent;
  let complianceService: jasmine.SpyObj<ComplianceService>;

  beforeEach(async () => {
    complianceService = jasmine.createSpyObj<ComplianceService>('ComplianceService', ['exportReport']);
    complianceService.exportReport.and.returnValue(
      of(new Blob(['{"ok":true}'], { type: 'application/json' }))
    );

    const apiKeyService = jasmine.createSpyObj<ApiKeyService>('ApiKeyService', [
      'getKey',
      'hasKey',
      'setKey',
      'clearKey',
    ]);
    apiKeyService.getKey.and.returnValue('agr_sk_test');
    apiKeyService.hasKey.and.returnValue(true);

    const orgService = jasmine.createSpyObj<OrgService>('OrgService', [
      'getMe',
      'getUsage',
      'getSso',
      'updateSso',
    ]);
    orgService.getMe.and.returnValue(
      of({
        id: 'org-1',
        name: 'Test Org',
        slug: 'test-org',
        plan: 'developer',
        eval_count: 3,
        eval_limit: 10,
        eval_warning_threshold_pct: 80,
        eval_soft_limit_enabled: true,
        eval_week_start: null,
        role: 'admin',
        auth_mode: 'api_key',
        auth_expires_at: null,
        sso_enabled: false,
        sso_provider: null,
        sso_domains: [],
        sso_default_role: 'viewer',
        sso_auto_join: false,
        created_at: '2026-03-27T00:00:00Z',
      })
    );
    orgService.getUsage.and.returnValue(
      of({
        org_id: 'org-1',
        total_evaluations: 3,
        eval_limit: 10,
        eval_warning_threshold_pct: 80,
        eval_soft_limit_enabled: true,
        usage_pct: 30,
        quota_state: 'ok',
        warning_message: null,
        per_agent: [],
      })
    );
    orgService.getSso.and.returnValue(
      of({
        enabled: false,
        provider: null,
        metadata_url: null,
        metadata_xml: null,
        entity_id: null,
        domains: [],
        default_role: 'viewer',
        auto_join: false,
      })
    );

    const clerkService = jasmine.createSpyObj<ClerkService>('ClerkService', ['fetchApiKey']);

    await TestBed.configureTestingModule({
      imports: [SettingsComponent],
      providers: [
        { provide: ApiKeyService, useValue: apiKeyService },
        { provide: OrgService, useValue: orgService },
        { provide: ClerkService, useValue: clerkService },
        { provide: ComplianceService, useValue: complianceService },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(SettingsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('downloads the compliance export as JSON', () => {
    const anchor = document.createElement('a');
    spyOn(anchor, 'click');
    const createObjectURL = spyOn(URL, 'createObjectURL').and.returnValue('blob:test');
    const revokeObjectURL = spyOn(URL, 'revokeObjectURL');
    const realCreateElement = document.createElement.bind(document);
    spyOn(document, 'createElement').and.callFake(((tagName: string): HTMLElement => {
      if (tagName === 'a') {
        return anchor;
      }
      return realCreateElement(tagName);
    }) as typeof document.createElement);

    component.downloadComplianceExport();

    expect(complianceService.exportReport).toHaveBeenCalledWith({
      format: 'json',
      period_days: 30,
    });
    expect(createObjectURL).toHaveBeenCalled();
    expect(anchor.download).toBe('agr-compliance-report.json');
    expect(anchor.click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test');
    expect(component.complianceExportError()).toBe('');
    expect(component.exportingCompliance()).toBeFalse();
  });
});
