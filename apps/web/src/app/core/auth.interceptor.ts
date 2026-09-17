import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, from, switchMap, throwError } from 'rxjs';

import { AuthService } from './auth.service';

/** Endpoints that establish a session and must not trigger a refresh attempt. */
const AUTH_ENDPOINTS = ['/auth/magic-link', '/auth/refresh', '/auth/sign-out'];

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const token = auth.token();
  const authorized = token
    ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
    : request;

  return next(authorized).pipe(
    catchError((error: unknown) => {
      const isAuthCall = AUTH_ENDPOINTS.some((path) => request.url.includes(path));
      const isExpired = error instanceof HttpErrorResponse && error.status === 401 && !isAuthCall;

      if (!isExpired) {
        return throwError(() => error);
      }

      // Access tokens are short-lived by design, so a 401 mid-session is
      // expected rather than exceptional: refresh once and replay the request.
      return from(auth.refresh()).pipe(
        switchMap(() => {
          const renewed = auth.token();
          return next(
            renewed
              ? request.clone({ setHeaders: { Authorization: `Bearer ${renewed}` } })
              : request,
          );
        }),
        catchError((refreshError: unknown) => {
          void router.navigate(['/sign-in'], {
            queryParams: { reason: 'session-expired' },
          });
          return throwError(() => refreshError);
        }),
      );
    }),
  );
};
