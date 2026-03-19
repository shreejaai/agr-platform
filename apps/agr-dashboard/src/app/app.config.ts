import { APP_INITIALIZER, ApplicationConfig } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideAnimations } from '@angular/platform-browser/animations';
import { routes } from './app.routes';
import { apiKeyInterceptor } from './core/http/api-key.interceptor';
import { errorInterceptor } from './core/http/error.interceptor';
import { ClerkService } from './core/auth/clerk.service';

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withInterceptors([apiKeyInterceptor, errorInterceptor])),
    provideAnimations(),
    {
      provide: APP_INITIALIZER,
      useFactory: (clerk: ClerkService) => () => clerk.init(),
      deps: [ClerkService],
      multi: true,
    },
  ],
};
