import { TestBed } from '@angular/core/testing';
import { ApiKeyService } from './api-key.service';

describe('ApiKeyService', () => {
  let service: ApiKeyService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    service = TestBed.inject(ApiKeyService);
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('hasKey() should return false when no key is set', () => {
    expect(service.hasKey()).toBeFalse();
  });

  it('setKey() should store the key and hasKey() should return true', () => {
    service.setKey('agr_sk_testkey');
    expect(service.hasKey()).toBeTrue();
  });

  it('getKey() should return the stored key', () => {
    service.setKey('agr_sk_testkey');
    expect(service.getKey()).toBe('agr_sk_testkey');
  });

  it('clearKey() should remove the key', () => {
    service.setKey('agr_sk_testkey');
    service.clearKey();
    expect(service.hasKey()).toBeFalse();
    expect(service.getKey()).toBeNull();
  });
});
