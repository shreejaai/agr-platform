import { AGRAuthError, AGRError, AGRRateLimitError } from "../errors";

describe("AGRError", () => {
  it("stores message and statusCode", () => {
    const err = new AGRError("something broke", 500);
    expect(err.message).toBe("something broke");
    expect(err.statusCode).toBe(500);
    expect(err.name).toBe("AGRError");
  });

  it("statusCode is optional", () => {
    const err = new AGRError("oops");
    expect(err.statusCode).toBeUndefined();
  });

  it("is instanceof Error and AGRError", () => {
    const err = new AGRError("x");
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(AGRError);
  });
});

describe("AGRAuthError", () => {
  it("has statusCode 401 and correct name", () => {
    const err = new AGRAuthError("unauthorized");
    expect(err.statusCode).toBe(401);
    expect(err.name).toBe("AGRAuthError");
    expect(err.message).toBe("unauthorized");
  });

  it("is instanceof AGRError and AGRAuthError", () => {
    const err = new AGRAuthError("nope");
    expect(err).toBeInstanceOf(AGRError);
    expect(err).toBeInstanceOf(AGRAuthError);
  });
});

describe("AGRRateLimitError", () => {
  it("has statusCode 429, name, upgradeUrl", () => {
    const err = new AGRRateLimitError("too many", "https://agr.dev/pricing");
    expect(err.statusCode).toBe(429);
    expect(err.name).toBe("AGRRateLimitError");
    expect(err.message).toBe("too many");
    expect(err.upgradeUrl).toBe("https://agr.dev/pricing");
  });

  it("upgradeUrl is optional", () => {
    const err = new AGRRateLimitError("slow down");
    expect(err.upgradeUrl).toBeUndefined();
  });

  it("is instanceof AGRError and AGRRateLimitError", () => {
    const err = new AGRRateLimitError("x");
    expect(err).toBeInstanceOf(AGRError);
    expect(err).toBeInstanceOf(AGRRateLimitError);
  });
});
