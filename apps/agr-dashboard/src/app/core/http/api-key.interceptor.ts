import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { ApiKeyService } from '../../services/api-key.service';

export const apiKeyInterceptor: HttpInterceptorFn = (req, next) => {
  const apiKeyService = inject(ApiKeyService);
  const key = apiKeyService.getKey();

  // Don't override if the request already carries its own Authorization header
  // (e.g. the Clerk session JWT sent by /v1/clerk/api-key to exchange for agr_sk_)
  if (key && req.url.startsWith('/v1') && !req.headers.has('Authorization')) {
    const cloned = req.clone({
      setHeaders: { Authorization: `Bearer ${key}` },
    });
    return next(cloned);
  }
  return next(req);
};
