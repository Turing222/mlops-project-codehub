import { describe, expect, it, beforeEach, vi } from 'vitest';
import {
  clearRecentRepoRuns,
  listRecentRepoRuns,
  upsertRecentRepoRun,
  type RecentRepoRun,
} from './recent-runs';

const STORAGE_KEY = 'DEWFLOW_RECENT_REPO_RUNS';

function makeRun(overrides: Partial<RecentRepoRun> = {}): RecentRepoRun {
  return {
    runId: 'run-1',
    owner: 'acme',
    repo: 'demo',
    repoUrl: 'https://github.com/acme/demo',
    projectName: 'Demo',
    likelyProjectType: 'product_candidate',
    hypeRisk: 'low',
    stars: 10,
    timestamp: 1_700_000_000_000,
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('listRecentRepoRuns', () => {
  it('returns empty array when storage has no data', () => {
    expect(listRecentRepoRuns()).toEqual([]);
  });

  it('returns valid stored data', () => {
    const runs = [makeRun(), makeRun({ runId: 'run-2', repoUrl: 'https://github.com/acme/other' })];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(runs));
    expect(listRecentRepoRuns()).toEqual(runs);
  });

  it('returns empty array for invalid JSON', () => {
    localStorage.setItem(STORAGE_KEY, '{not-json');
    expect(listRecentRepoRuns()).toEqual([]);
    // Does not delete the raw value on read failure.
    expect(localStorage.getItem(STORAGE_KEY)).toBe('{not-json');
  });

  it('returns empty array when schema does not match', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([{ foo: 'bar' }]));
    expect(listRecentRepoRuns()).toEqual([]);
  });

  it('does not throw when localStorage.getItem throws', () => {
    const originalGetItem = Storage.prototype.getItem;
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (
      this: Storage,
      key: string,
    ) {
      if (key === STORAGE_KEY) {
        throw new Error('quota');
      }
      return originalGetItem.call(this, key);
    });
    expect(() => listRecentRepoRuns()).not.toThrow();
    expect(listRecentRepoRuns()).toEqual([]);
  });
});

describe('upsertRecentRepoRun', () => {
  it('dedupes by runId', () => {
    upsertRecentRepoRun(makeRun({ runId: 'same', projectName: 'Old' }));
    const next = upsertRecentRepoRun(makeRun({ runId: 'same', projectName: 'New' }));
    expect(next).toHaveLength(1);
    expect(next[0].projectName).toBe('New');
  });

  it('dedupes by repoUrl', () => {
    upsertRecentRepoRun(makeRun({ runId: 'a', repoUrl: 'https://github.com/acme/demo' }));
    const next = upsertRecentRepoRun(
      makeRun({ runId: 'b', repoUrl: 'https://github.com/acme/demo', projectName: 'Updated' }),
    );
    expect(next).toHaveLength(1);
    expect(next[0].runId).toBe('b');
    expect(next[0].projectName).toBe('Updated');
  });

  it('puts the newest record first', () => {
    upsertRecentRepoRun(makeRun({ runId: 'old', repoUrl: 'https://github.com/a/old' }));
    const next = upsertRecentRepoRun(makeRun({ runId: 'new', repoUrl: 'https://github.com/a/new' }));
    expect(next.map((item) => item.runId)).toEqual(['new', 'old']);
  });

  it('caps the list at 10 items', () => {
    for (let i = 0; i < 12; i += 1) {
      upsertRecentRepoRun(
        makeRun({
          runId: `run-${i}`,
          repoUrl: `https://github.com/acme/repo-${i}`,
        }),
      );
    }
    const list = listRecentRepoRuns();
    expect(list).toHaveLength(10);
    expect(list[0].runId).toBe('run-11');
  });

  it('does not throw when localStorage.setItem throws', () => {
    const originalSetItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
      this: Storage,
      key: string,
      value: string,
    ) {
      // Only fail the recent-runs key so auth-store persist teardown still works.
      if (key === STORAGE_KEY) {
        throw new Error('quota');
      }
      return originalSetItem.call(this, key, value);
    });
    expect(() => upsertRecentRepoRun(makeRun())).not.toThrow();
    expect(upsertRecentRepoRun(makeRun({ runId: 'x' }))).toEqual([
      expect.objectContaining({ runId: 'x' }),
    ]);
  });
});

describe('clearRecentRepoRuns', () => {
  it('removes the storage value', () => {
    upsertRecentRepoRun(makeRun());
    clearRecentRepoRuns();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(listRecentRepoRuns()).toEqual([]);
  });

  it('does not throw when localStorage.removeItem throws', () => {
    const originalRemoveItem = Storage.prototype.removeItem;
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(function (
      this: Storage,
      key: string,
    ) {
      if (key === STORAGE_KEY) {
        throw new Error('blocked');
      }
      return originalRemoveItem.call(this, key);
    });
    expect(() => clearRecentRepoRuns()).not.toThrow();
  });
});
