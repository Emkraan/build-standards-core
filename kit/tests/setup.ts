import { cleanup, configure } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';
import { defaultStore } from '../../shell-packages/app-client/src';
import { installMatchMedia, resetMedia } from './helpers';

installMatchMedia();

// jsdom has no ResizeObserver. recharts and React Flow measure through one; a stub that never
// reports is enough, since jsdom has no layout to report.
if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, writable: true, value: ResizeObserverStub });
}

// Keep query errors to one line instead of a full DOM dump.
configure({
  getElementError: (message) => {
    const error = new Error((message ?? '').split('\n\n')[0]);
    error.name = 'TestingLibraryElementError';
    return error;
  },
});

beforeEach(() => {
  resetMedia();
});

afterEach(() => {
  cleanup();
  defaultStore.clear();
  window.localStorage.clear();
  window.sessionStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('data-app-accent');
  document.documentElement.removeAttribute('style');
  document.body.removeAttribute('style');
});
