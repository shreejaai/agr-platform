import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';
import { authGuard } from './auth.guard';
import { ClerkService } from './clerk.service';

describe('authGuard', () => {
  let mockClerkService: jasmine.SpyObj<ClerkService>;
  let mockRouter: jasmine.SpyObj<Router>;

  const mockRoute = {} as ActivatedRouteSnapshot;
  const mockState = { url: '/home' } as RouterStateSnapshot;

  beforeEach(() => {
    mockClerkService = jasmine.createSpyObj('ClerkService', ['isSignedIn']);
    mockRouter = jasmine.createSpyObj('Router', ['createUrlTree']);
    mockRouter.createUrlTree.and.returnValue({} as never);

    TestBed.configureTestingModule({
      providers: [
        { provide: ClerkService, useValue: mockClerkService },
        { provide: Router, useValue: mockRouter },
      ],
    });
  });

  it('should allow navigation when user is signed in', () => {
    mockClerkService.isSignedIn.and.returnValue(true);
    const result = TestBed.runInInjectionContext(() =>
      authGuard(mockRoute, mockState)
    );
    expect(result).toBeTrue();
  });

  it('should redirect to /login when user is not signed in', () => {
    mockClerkService.isSignedIn.and.returnValue(false);
    const result = TestBed.runInInjectionContext(() =>
      authGuard(mockRoute, mockState)
    );
    expect(mockRouter.createUrlTree).toHaveBeenCalledWith(['/login']);
    expect(result).not.toBeTrue();
  });
});
