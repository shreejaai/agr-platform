import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { ClerkService } from './clerk.service';

/** Prevent signed-in users from landing on /login. */
export const publicGuard: CanActivateFn = () => {
  const clerk = inject(ClerkService);
  const router = inject(Router);
  if (clerk.isSignedIn()) return router.createUrlTree(['/home']);
  return true;
};
