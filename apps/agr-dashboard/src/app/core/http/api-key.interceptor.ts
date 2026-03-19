import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { ApiKeyService } from '../../services/api-key.service';

export const apiKeyInterceptor: HttpInterceptorFn = (req, next) => {
  const apiKeyService = inject(ApiKeyService);
  const key = apiKeyService.getKey();

  if (key && req.url.startsWith('/v1')) {
    const cloned = req.clone({
      setHeaders: { Authorization: `Bearer ${key}` },
    });
    return next(cloned);
  }
  return next(req);
};
