import { Routes } from '@angular/router';

import { onboardedGuard, onboardingPendingGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    loadComponent: () => import('./features/landing/landing').then((m) => m.Landing),
    title: 'eoehelp — track your EoE, and give your doctor the full picture',
  },
  {
    path: 'sign-in',
    loadComponent: () => import('./features/auth/sign-in').then((m) => m.SignIn),
    title: 'Sign in — eoehelp',
  },
  {
    path: 'verify',
    loadComponent: () => import('./features/auth/verify').then((m) => m.Verify),
    title: 'Signing you in — eoehelp',
  },
  {
    path: 'welcome',
    canActivate: [onboardingPendingGuard],
    loadComponent: () => import('./features/onboarding/welcome').then((m) => m.Welcome),
    title: 'Set up your record — eoehelp',
  },
  {
    path: 'today',
    canActivate: [onboardedGuard],
    loadComponent: () => import('./features/today/today').then((m) => m.Today),
    title: 'Today — eoehelp',
  },
  {
    // The date is part of the URL so a reminder notification, a catch-up link, or
    // a bookmark can all deep-link straight into the right day.
    path: 'log/:entryDate',
    canActivate: [onboardedGuard],
    loadComponent: () => import('./features/log/log').then((m) => m.Log),
    title: 'Daily log — eoehelp',
  },
  {
    path: 'medications',
    canActivate: [onboardedGuard],
    loadComponent: () => import('./features/medications/medications').then((m) => m.Medications),
    title: 'Medications — eoehelp',
  },
  {
    path: 'insights',
    canActivate: [onboardedGuard],
    loadComponent: () => import('./features/insights/insights').then((m) => m.Insights),
    title: 'Insights — eoehelp',
  },
  {
    path: 'log',
    canActivate: [onboardedGuard],
    loadComponent: () => import('./features/log/log').then((m) => m.Log),
    title: "Today's log — eoehelp",
  },
  { path: '**', redirectTo: '' },
];
