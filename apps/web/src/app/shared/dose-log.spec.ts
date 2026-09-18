import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { MedicationTodayItem } from '../core/api-types';
import { MedicationService } from '../core/medication.service';
import { DoseLog } from './dose-log';

function item(doses: MedicationTodayItem['doses_today']): MedicationTodayItem {
  return {
    medication_id: 'med-1',
    medication_code: 'budesonide_oral_suspension',
    generic_name: 'Budesonide oral suspension',
    dose_label: '2 mg',
    frequency: 'twice_daily',
    expected_today: 2,
    doses_today: doses,
  };
}

class StubMedications {
  readonly undone: string[] = [];
  view: MedicationTodayItem[] = [];

  async today() {
    return { on_date: '2026-09-18', items: this.view };
  }

  async undoDose(id: string): Promise<void> {
    this.undone.push(id);
  }
}

type Internals = { undo(item: MedicationTodayItem): Promise<void> };

describe('DoseLog', () => {
  let stub: StubMedications;

  beforeEach(async () => {
    stub = new StubMedications();
    await TestBed.configureTestingModule({
      imports: [DoseLog],
      providers: [provideRouter([]), { provide: MedicationService, useValue: stub }],
    }).compileComponents();
  });

  it('can undo a mistaken "Skipped" tap, not only a taken dose', async () => {
    const skipped = item([
      {
        id: 'dose-1',
        medication_id: 'med-1',
        taken_at: '2026-09-18T08:00:00Z',
        status: 'taken',
      },
      {
        id: 'dose-2',
        medication_id: 'med-1',
        taken_at: '2026-09-18T20:00:00Z',
        status: 'skipped',
      },
    ]);
    stub.view = [skipped];
    const fixture = TestBed.createComponent(DoseLog);
    await fixture.whenStable();
    fixture.detectChanges();

    const undo = (fixture.nativeElement as HTMLElement).querySelector(
      '[aria-label^="Undo the last entry"]',
    );
    expect(undo).not.toBeNull();

    await (fixture.componentInstance as unknown as Internals).undo(skipped);
    expect(stub.undone).toEqual(['dose-2']);
  });

  it('offers no undo before anything is logged', async () => {
    stub.view = [item([])];
    const fixture = TestBed.createComponent(DoseLog);
    await fixture.whenStable();
    fixture.detectChanges();
    const undo = (fixture.nativeElement as HTMLElement).querySelector(
      '[aria-label^="Undo the last entry"]',
    );
    expect(undo).toBeNull();
  });
});
