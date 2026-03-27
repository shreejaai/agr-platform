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
  });
});
