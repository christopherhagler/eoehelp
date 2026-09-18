import { inject } from '@angular/core';
import { CanActivateFn, Router, RouterStateSnapshot, UrlTree } from '@angular/router';

import { AuthService } from './auth.service';

/**
 * Resolve to true, or to the sign-in redirect.
 *
 * Returns the narrow `true | UrlTree` rather than the router's full GuardResult
 * so the guards below can compose by awaiting it — GuardResult includes an
 * Observable, which would not be assignable back into CanActivateFn.
 *
 * A full page load into a protected route arrives before the refresh cookie has
 * been exchanged, so this waits for restoration rather than bouncing someone to
 * sign-in when they are in fact still signed in.
 */
async function requireSession(
  auth: AuthService,
  router: Router,
  state: RouterStateSnapshot,
): Promise<true | UrlTree> {
  if (auth.isRestoring()) {
    await auth.restore();
  }
  if (auth.isSignedIn()) {
    return true;
  }
  return router.createUrlTree(['/sign-in'], {
    queryParams: { returnTo: state.url },
  });
}

export const authGuard: CanActivateFn = (_route, state) =>
  requireSession(inject(AuthService), inject(Router), state);

/**
 * Signed in *and* onboarded. Everything patient-scoped needs both: without a
 * patient record the access token carries no patient id and the API refuses every
 * /me route, so sending someone there would show them a broken screen instead of
 * the form that fixes it.
 */
export const onboardedGuard: CanActivateFn = async (_route, state) => {
  // inject() runs before the first await, while the injection context is active.
  const auth = inject(AuthService);
  const router = inject(Router);

  const session = await requireSession(auth, router, state);
  if (session !== true) {
    return session;
  }
  return auth.needsOnboarding() ? router.createUrlTree(['/welcome']) : true;
};

/** The onboarding screen itself: pointless once there is a patient record. */
export const onboardingPendingGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const session = await requireSession(auth, router, state);
  if (session !== true) {
    return session;
  }
  return auth.needsOnboarding() ? true : router.createUrlTree(['/today']);
};
