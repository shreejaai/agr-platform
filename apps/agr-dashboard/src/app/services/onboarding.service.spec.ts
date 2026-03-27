import { TestBed } from '@angular/core/testing';
import { OnboardingService } from './onboarding.service';

describe('OnboardingService', () => {
  let service: OnboardingService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    service = TestBed.inject(OnboardingService);
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('starts in the active state by default', () => {
    expect(service.dismissed()).toBeFalse();
  });

  it('persists dismissal in local storage', () => {
    service.dismiss();

    expect(service.dismissed()).toBeTrue();
    expect(localStorage.getItem('agr_onboarding_dismissed')).toBe('true');
  });

  it('clears dismissal when resumed', () => {
    service.dismiss();
    service.resume();

    expect(service.dismissed()).toBeFalse();
    expect(localStorage.getItem('agr_onboarding_dismissed')).toBeNull();
  });
});
