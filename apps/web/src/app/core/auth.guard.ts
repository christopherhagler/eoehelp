import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  // A full page load into a protected route arrives before the refresh cookie
  // has been exchanged, so wait for restoration rather than bouncing the user
  // to sign-in when they are in fact still signed in.
  if (auth.isRestoring()) {
    await auth.restore();
  }

  if (auth.isSignedIn()) {
    return true;
  }

  return router.createUrlTree(['/sign-in'], {
    queryParams: { returnTo: state.url },
  });
};
