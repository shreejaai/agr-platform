import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';
import { apiKeyGuard } from './api-key.guard';
import { ApiKeyService } from '../../services/api-key.service';

describe('apiKeyGuard', () => {
  let mockApiKeyService: jasmine.SpyObj<ApiKeyService>;
  let mockRouter: jasmine.SpyObj<Router>;

  const mockRoute = {} as ActivatedRouteSnapshot;
  const mockState = { url: '/approvals' } as RouterStateSnapshot;

  beforeEach(() => {
    mockApiKeyService = jasmine.createSpyObj('ApiKeyService', ['hasKey']);
    mockRouter = jasmine.createSpyObj('Router', ['createUrlTree']);
    mockRouter.createUrlTree.and.returnValue({} as never);

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiKeyService, useValue: mockApiKeyService },
        { provide: Router, useValue: mockRouter },
      ],
    });
  });

  it('should allow navigation when API key is present', () => {
    mockApiKeyService.hasKey.and.returnValue(true);
    const result = TestBed.runInInjectionContext(() =>
      apiKeyGuard(mockRoute, mockState)
    );
    expect(result).toBeTrue();
  });

  it('should redirect to /settings when API key is missing', () => {
    mockApiKeyService.hasKey.and.returnValue(false);
    const result = TestBed.runInInjectionContext(() =>
      apiKeyGuard(mockRoute, mockState)
    );
    expect(mockRouter.createUrlTree).toHaveBeenCalledWith(['/settings']);
    expect(result).not.toBeTrue();
  });
});
