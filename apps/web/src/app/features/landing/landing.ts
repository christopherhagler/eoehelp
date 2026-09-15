import { Component } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';

import { Logo } from '../../shared/logo';

interface Capability {
  readonly icon: string;
  readonly title: string;
  readonly body: string;
}

@Component({
  selector: 'app-landing',
  imports: [RouterLink, MatButtonModule, MatCardModule, MatIconModule, Logo],
  templateUrl: './landing.html',
})
export class Landing {
  protected readonly capabilities: readonly Capability[] = [
    {
      icon: 'timer',
      title: 'A daily log that takes under a minute',
      body:
        'Did you eat solid food? Did anything get stuck? Most days are two taps. ' +
        'The questions follow the Dysphagia Symptom Questionnaire — the measure ' +
        'used to judge whether EoE treatments are working.',
    },
    {
      icon: 'restaurant',
      title: 'Elimination diets, tracked properly',
      body:
        'Record phases and reintroductions food by food, with the outcome of each ' +
        'challenge and the biopsy that confirmed it. This is what patients most ' +
        'often lose track of between appointments.',
    },
    {
      icon: 'biotech',
      title: 'Your endoscopy history in sequence',
      body:
        'EREFS sub-scores and peak eosinophil counts from every procedure, kept in ' +
        'order so change over time is visible instead of buried across years of ' +
        'separate reports.',
    },
    {
      icon: 'medication',
      title: 'Medications and real adherence',
      body:
        'Proton pump inhibitors, swallowed steroids, dupilumab. Adherence is ' +
        'measured against what the schedule actually expected, so a biweekly ' +
        'injection is not judged like a twice-daily pill.',
    },
    {
      icon: 'description',
      title: 'A summary you choose to share',
      body:
        'Generate a clear report and hand your doctor a link that expires and that ' +
        'you can revoke. No account needed on their side, and you can see every ' +
        'time it was opened.',
    },
    {
      icon: 'lock',
      title: 'Your record stays yours',
      body:
        'Nothing reaches a doctor, a researcher, or anyone else unless you choose ' +
        'it. You can withdraw that choice or delete your account at any time, and ' +
        'the deletion is real.',
    },
  ];
}
