import { of } from 'rxjs';
import { provideRouter } from '@angular/router';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AgentService } from '../../services/agent.service';
import { PolicyService, SimulateResult } from '../../services/policy.service';
import { PolicySimulatorComponent } from './policy-simulator.component';

describe('PolicySimulatorComponent', () => {
  let policyService: jasmine.SpyObj<PolicyService>;
  let agentService: jasmine.SpyObj<AgentService>;

  beforeEach(async () => {
    policyService = jasmine.createSpyObj<PolicyService>('PolicyService', ['simulatePolicy']);
    agentService = jasmine.createSpyObj<AgentService>('AgentService', ['list']);
    agentService.list.and.returnValue(
      of([
        {
          id: 'agent-record-1',
          org_id: 'org-1',
          agent_id: 'support-agent',
          metadata: { name: 'Support Agent' },
          active: true,
          created_at: '2026-03-27T00:00:00Z',
          updated_at: '2026-03-27T00:00:00Z',
        },
      ]),
    );

    await TestBed.configureTestingModule({
      imports: [PolicySimulatorComponent],
      providers: [
        provideRouter([]),
        { provide: PolicyService, useValue: policyService },
        { provide: AgentService, useValue: agentService },
      ],
    }).compileComponents();
  });

  function createComponent(): {
    component: PolicySimulatorComponent;
    fixture: ComponentFixture<PolicySimulatorComponent>;
  } {
    const fixture = TestBed.createComponent(PolicySimulatorComponent);
    fixture.detectChanges();
    return { component: fixture.componentInstance, fixture };
  }

  it('shows validation errors before simulating', () => {
    const { component } = createComponent();

    component.simulate();

    expect(policyService.simulatePolicy).not.toHaveBeenCalled();
    expect(component.validationErrors()).toEqual([
      'Action is required.',
      'Resource is required.',
    ]);
  });

  it('parses typed context values before calling the API', () => {
    const mockResult: SimulateResult = {
      decision: 'APPROVAL_REQUIRED',
      reason: 'Requires manager review.',
      policy_id: 'policy-123',
      risk_score: 62,
      risk_level: 'medium',
      risk_factors: { sensitive_data: 30, action_severity: 32 },
      compliance_findings: [
        {
          plugin: 'audit_trail_check',
          standard: 'SOC2',
          rule_id: 'CC6.1',
          severity: 'warning',
          message: 'Action is specific and auditable.',
          passed: true,
          remediation_steps: [],
          severity_level: 'low',
          compliance_score: 100,
        },
      ],
      decision_trace: {
        policy_source: 'cedar_cli',
        matched_policy_id: 'policy-123',
        cedar_decision: 'ALLOW',
        risk_score: 62,
        risk_level: 'medium',
        risk_override: true,
        fallback_used: false,
        fallback_reason: null,
      },
    };
    policyService.simulatePolicy.and.returnValue(of(mockResult));

    const { component } = createComponent();
    component.agentId.set('support-agent');
    component.action.set('transfer_funds');
    component.resource.set('bank-account-001');
    component.contextEntries.set([
      { key: 'amount', value: '42' },
      { key: 'approved', value: 'true' },
      { key: 'metadata', value: '{"env":"prod"}' },
    ]);

    component.simulate();

    expect(policyService.simulatePolicy).toHaveBeenCalledWith({
      agent_id: 'support-agent',
      action: 'transfer_funds',
      resource: 'bank-account-001',
      context: {
        amount: 42,
        approved: true,
        metadata: { env: 'prod' },
      },
    });
    expect(component.result()).toEqual(mockResult);
  });

  it('renders the matched policy and explanation after success', () => {
    const mockResult: SimulateResult = {
      decision: 'DENY',
      reason: 'Denied by policy.',
      policy_id: 'policy-deny-1',
      risk_score: 88,
      risk_level: 'high',
      risk_factors: { sensitive_data: 50, action_severity: 38 },
      compliance_findings: [
        {
          plugin: 'audit_trail_check',
          standard: 'EU_AI_ACT',
          rule_id: 'ART-13',
          severity: 'warning',
          message: 'Agent ID is missing or too generic.',
          passed: false,
          remediation_steps: [
            'Use a stable, descriptive `agent_id` instead of a generic identifier.',
            'Register or update the agent metadata so audit records can identify the actor.',
          ],
          severity_level: 'high',
          compliance_score: 38,
        },
      ],
      decision_trace: {
        policy_source: 'python_fallback',
        matched_policy_id: 'policy-deny-1',
        cedar_decision: 'DENY',
        risk_score: 88,
        risk_level: 'high',
        risk_override: false,
        fallback_used: true,
        fallback_reason: 'Cedar CLI unavailable',
      },
    };
    policyService.simulatePolicy.and.returnValue(of(mockResult));

    const { component, fixture } = createComponent();
    component.agentId.set('support-agent');
    component.action.set('delete_customer_record');
    component.resource.set('crm-record-7');

    component.simulate();
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Denied by policy.');
    expect(text).toContain('policy-deny-1');
    expect(text).toContain('Fallback evaluator was used');
    expect(text).toContain('Remediation steps');
    expect(text).toContain('Use a stable, descriptive `agent_id` instead of a generic identifier.');
  });
});
