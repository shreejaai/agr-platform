import { Component, OnInit, inject, ChangeDetectionStrategy } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ClerkService } from './core/auth/clerk.service';

@Component({
  selector: 'agr-root',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet],
  template: `<router-outlet />`,
})
export class AppComponent implements OnInit {
  private clerk = inject(ClerkService);

  async ngOnInit(): Promise<void> {
    await this.clerk.init();
  }
}
