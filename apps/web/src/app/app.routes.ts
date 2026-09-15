import { Routes } from '@angular/router';

import { authGuard } from './core/auth.guard';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    loadComponent: () =>
      import('./features/landing/landing').then((m) => m.Landing),
    title: 'eoehelp — track your EoE, and give your doctor the full picture',
  },
  {
    path: 'sign-in',
    loadComponent: () =>
      import('./features/auth/sign-in').then((m) => m.SignIn),
    title: 'Sign in — eoehelp',
  },
  {
    path: 'verify',
    loadComponent: () => import('./features/auth/verify').then((m) => m.Verify),
    title: 'Signing you in — eoehelp',
  },
  {
    path: 'today',
    canActivate: [authGuard],
    loadComponent: () => import('./features/today/today').then((m) => m.Today),
    title: "Today's log — eoehelp",
  },
  { path: '**', redirectTo: '' },
];
