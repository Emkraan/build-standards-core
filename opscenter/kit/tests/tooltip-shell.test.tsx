/* AppShell mounts the tooltip layer once when asked (tooltipLayer, default off). Every [data-tip] and
   native title in an app then shows the kit tip with no wiring, an app that mounts its own layer keeps
   working, and a second layer never draws a second tip. Without the prop nothing mounts and nothing is
   adopted, so a consumer that does not ask sees what it saw before. */
import { act, fireEvent, render } from '@testing-library/react';
import axe from 'axe-core';
import { StrictMode, useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell, Button, Header, Rail, TooltipLayer } from '../src';

function Shell({ tooltipLayer = true, extra }: { tooltipLayer?: boolean; extra?: boolean }) {
  return (
    <AppShell
      rail={<Rail brandName="Test" brandMark="T" version="1.0.0" />}
      header={<Header title="Console" />}
      {...(tooltipLayer ? { tooltipLayer } : {})}
    >
      <button type="button" data-tip="Refresh the list">
        Refresh
      </button>
      <button type="button" title="Native title tip">
        Native
      </button>
      {extra ? <TooltipLayer /> : null}
    </AppShell>
  );
}

const hover = (el: Element) => {
  fireEvent.pointerOver(el);
  act(() => {
    vi.advanceTimersByTime(2000);
  });
};
const tips = () => document.querySelectorAll('.tooltip');

describe('AppShell and the tooltip layer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows a data-tip with no layer mounted by the app', () => {
    const { getByText } = render(<Shell />);
    hover(getByText('Refresh'));
    expect(tips().length).toBe(1);
    expect(tips()[0]?.textContent).toContain('Refresh the list');
  });

  it('adopts a native title, so the browser tip never shows', () => {
    const { getByText } = render(<Shell />);
    const native = getByText('Native');
    hover(native);
    expect(native.hasAttribute('title')).toBe(false);
    expect(native.getAttribute('data-tip')).toBe('Native title tip');
    expect(tips()[0]?.textContent).toContain('Native title tip');
  });

  it('shows the tip on keyboard focus at once', () => {
    const { getByText } = render(<Shell />);
    const button = getByText('Refresh');
    // jsdom has no :focus-visible, so the layer treats every focus as a keyboard focus.
    act(() => button.focus());
    expect(tips().length).toBe(1);
  });

  it('is off by default: no layer, no tip, a native title kept as it was', () => {
    const { getByText } = render(
      <AppShell rail={<Rail brandName="Test" brandMark="T" version="1.0.0" />} header={<Header title="Console" />}>
        <button type="button" data-tip="Refresh the list">
          Refresh
        </button>
        <button type="button" title="Native title tip">
          Native
        </button>
      </AppShell>,
    );
    hover(getByText('Refresh'));
    expect(tips().length).toBe(0);
    const native = getByText('Native');
    hover(native);
    expect(tips().length).toBe(0);
    expect(native.getAttribute('title')).toBe('Native title tip');
    expect(native.hasAttribute('data-tip')).toBe(false);
  });

  it('keeps an app\'s own layer working when the shell does not mount one', () => {
    const { getByText } = render(<Shell tooltipLayer={false} extra />);
    hover(getByText('Refresh'));
    expect(tips().length).toBe(1);
  });

  it('never draws a second tip when the app also mounts a layer', () => {
    const { getByText } = render(<Shell extra />);
    hover(getByText('Refresh'));
    expect(tips().length).toBe(1);
  });

  it('stays single under StrictMode and with several layers', () => {
    const { getByText } = render(
      <StrictMode>
        <Shell extra />
        <TooltipLayer />
      </StrictMode>,
    );
    hover(getByText('Refresh'));
    expect(tips().length).toBe(1);
  });

  it('hands over to the next layer when the active one unmounts', () => {
    function Swap() {
      const [first, setFirst] = useState(true);
      return (
        <>
          {first ? <TooltipLayer /> : null}
          <TooltipLayer />
          <button type="button" data-tip="Handed over" onClick={() => setFirst(false)}>
            Swap
          </button>
        </>
      );
    }
    const { getByText } = render(<Swap />);
    fireEvent.click(getByText('Swap'));
    hover(getByText('Swap'));
    expect(tips().length).toBe(1);
    expect(tips()[0]?.textContent).toContain('Handed over');
  });

  it('removes its listeners when the layer unmounts', () => {
    const add = vi.spyOn(document, 'addEventListener');
    const remove = vi.spyOn(document, 'removeEventListener');
    const { unmount } = render(<TooltipLayer />);
    const added = add.mock.calls.length;
    expect(added).toBeGreaterThan(0);
    unmount();
    expect(remove.mock.calls.length).toBeGreaterThanOrEqual(added);
  });

  it('has no axe violations with a tip showing', async () => {
    const { container, getByText } = render(<Shell />);
    hover(getByText('Refresh'));
    vi.useRealTimers();
    const res = await axe.run(container, { rules: { region: { enabled: false } } });
    expect(res.violations).toEqual([]);
  });

  it('is reachable from the Button data-tip the kit never showed before', () => {
    const { getByText } = render(
      <AppShell tooltipLayer rail={<Rail brandName="Test" brandMark="T" version="1.0.0" />}>
        <Button data-tip="Saves the form">Save</Button>
      </AppShell>,
    );
    hover(getByText('Save'));
    expect(tips()[0]?.textContent).toContain('Saves the form');
  });
});
