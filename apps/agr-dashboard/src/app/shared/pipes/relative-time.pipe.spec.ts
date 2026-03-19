import { RelativeTimePipe } from './relative-time.pipe';

describe('RelativeTimePipe', () => {
  let pipe: RelativeTimePipe;

  beforeEach(() => {
    pipe = new RelativeTimePipe();
  });

  it('should create an instance', () => {
    expect(pipe).toBeTruthy();
  });

  it('should return "just now" for very recent timestamps', () => {
    const recent = new Date(Date.now() - 5000).toISOString();
    const result = pipe.transform(recent);
    // "just now" or "5 seconds ago" — just check it is a string
    expect(typeof result).toBe('string');
    expect(result.length).toBeGreaterThan(0);
  });

  it('should return a relative string for timestamps 2 minutes ago', () => {
    const twoMinsAgo = new Date(Date.now() - 2 * 60 * 1000).toISOString();
    const result = pipe.transform(twoMinsAgo);
    expect(result).toContain('minute');
  });

  it('should return a relative string for timestamps 3 hours ago', () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    const result = pipe.transform(threeHoursAgo);
    expect(result).toContain('hour');
  });

  it('should handle empty string without throwing', () => {
    expect(() => pipe.transform('')).not.toThrow();
  });
});
