export class AGRError extends Error {
  readonly statusCode: number | undefined;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.name = "AGRError";
    this.statusCode = statusCode;
  }
}

export class AGRAuthError extends AGRError {
  constructor(message: string) {
    super(message, 401);
    this.name = "AGRAuthError";
  }
}

export class AGRRateLimitError extends AGRError {
  readonly upgradeUrl: string | undefined;

  constructor(message: string, upgradeUrl?: string) {
    super(message, 429);
    this.name = "AGRRateLimitError";
    this.upgradeUrl = upgradeUrl;
  }
}
