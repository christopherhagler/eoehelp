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
  // Public, and readable before an account exists. The slug routes are the
  // ones people link to; /legal/:documentId is the permanent link to the exact
  // version a consent record names.
  {
    path: 'terms',
    loadComponent: () => import('./features/legal/legal-document').then((m) => m.LegalDocument),
    data: { documentId: 'terms' },
    title: 'Terms of service — eoehelp',
  },
  {
    path: 'privacy',
    loadComponent: () => import('./features/legal/legal-document').then((m) => m.LegalDocument),
    data: { documentId: 'privacy' },
    title: 'Privacy policy — eoehelp',
  },
  {
    path: 'health-data',
    loadComponent: () => import('./features/legal/legal-document').then((m) => m.LegalDocument),
    data: { documentId: 'health-data' },
    title: 'Consumer Health Data Privacy Policy — eoehelp',
  },
  {
    path: 'legal/:documentId',
    loadComponent: () => import('./features/legal/legal-document').then((m) => m.LegalDocument),
    title: 'Legal — eoehelp',
  },
  { path: '**', redirectTo: '' },
];
