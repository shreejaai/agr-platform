import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { ApiKeyService } from '../../services/api-key.service';

export const apiKeyGuard: CanActivateFn = () => {
  const apiKey = inject(ApiKeyService);
  const router = inject(Router);
  if (apiKey.hasKey()) return true;
  return router.createUrlTree(['/settings']);
};
