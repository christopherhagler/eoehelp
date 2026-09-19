import { Component, ElementRef, OnDestroy, OnInit, output, signal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

/** The parts of the Shape Detection API used here; not yet in TypeScript's DOM lib. */
interface DetectedBarcode {
  readonly rawValue: string;
}
interface BarcodeDetectorLike {
  detect(source: HTMLVideoElement): Promise<DetectedBarcode[]>;
}
type BarcodeDetectorConstructor = new (options: { formats: string[] }) => BarcodeDetectorLike;

const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e'];
const SCAN_INTERVAL_MS = 250;

function detectorConstructor(): BarcodeDetectorConstructor | null {
  const candidate = (globalThis as { BarcodeDetector?: BarcodeDetectorConstructor })
    .BarcodeDetector;
  return candidate ?? null;
}

/** Whether this browser can scan at all. Safari on iOS cannot, yet. */
export function canScanBarcodes(): boolean {
  return (
    detectorConstructor() !== null &&
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

/**
 * Reads a product barcode from the camera.
 *
 * Uses the browser's built-in detector, so no image ever leaves the device and
 * no scanning library is shipped. Where the browser has no detector, the editor
 * offers typing the number instead.
 */
@Component({
  selector: 'app-barcode-scanner',
  imports: [MatButtonModule, MatIconModule],
  template: `
    <div class="flex flex-col gap-3">
      @if (error()) {
        <p role="alert" class="m-0 text-sm text-danger">{{ error() }}</p>
      } @else {
        <div class="relative overflow-hidden rounded-[22px] bg-black">
          <video
            #video
            class="block aspect-video w-full object-cover"
            muted
            playsinline
            aria-label="Camera view for scanning a barcode"
          ></video>
          <div
            class="pointer-events-none absolute inset-x-8 top-1/2 h-0.5 -translate-y-1/2
                   bg-brand/80"
            aria-hidden="true"
          ></div>
        </div>
        <p class="m-0 text-sm text-on-surface-variant" aria-live="polite">
          Point the camera at the barcode on the package.
        </p>
      }
      <button mat-button type="button" class="self-start !min-h-tap" (click)="cancelled.emit()">
        Cancel
      </button>
    </div>
  `,
})
export class BarcodeScanner implements OnInit, OnDestroy {
  readonly detected = output<string>();
  readonly cancelled = output<void>();

  private readonly video = viewChild<ElementRef<HTMLVideoElement>>('video');
  protected readonly error = signal<string | null>(null);

  private stream: MediaStream | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;

  async ngOnInit(): Promise<void> {
    const Detector = detectorConstructor();
    if (!Detector || !canScanBarcodes()) {
      this.error.set('This browser cannot scan barcodes. Type the number instead.');
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false,
      });
    } catch {
      this.error.set('The camera is not available. Check the permission, or type the number.');
      return;
    }
    const element = this.video()?.nativeElement;
    if (!element) {
      this.stop();
      return;
    }
    element.srcObject = this.stream;
    await element.play();

    const detector = new Detector({ formats: FORMATS });
    let busy = false;
    this.timer = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const [first] = await detector.detect(element);
        if (first?.rawValue) {
          this.stop();
          this.detected.emit(first.rawValue);
        }
      } catch {
        // A frame that cannot be read is normal while the camera moves.
      } finally {
        busy = false;
      }
    }, SCAN_INTERVAL_MS);
  }

  ngOnDestroy(): void {
    this.stop();
  }

  private stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    // Release the camera as soon as it is no longer needed, not when the page
    // closes: the indicator light is how a patient knows it is off.
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}
