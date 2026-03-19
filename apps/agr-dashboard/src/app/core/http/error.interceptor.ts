import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const router = inject(Router);
  return next(req).pipe(
    catchError((err) => {
      if (err.status === 401 && req.url.startsWith('/v1')) {
        // Invalid or missing API key — send to settings
        router.navigate(['/settings']);
      }
      return throwError(() => err);
    }),
  );
};
