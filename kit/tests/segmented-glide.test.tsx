/* Segmented draws its selected pill as one marker that glides to the pressed option
   (web-ui.md section 7), not as a fill on each option. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { Segmented } from '../src';

const OPTIONS = [
  { value: 'a', label: 'Day' },
  { value: 'b', label: 'Week' },
] as const;

function Harness() {
  const [value, setValue] = useState<'a' | 'b'>('a');
  return <Segmented options={OPTIONS} value={value} onChange={setValue} label="Range" />;
}

describe('Segmented glider', () => {
  it('renders one decorative marker and hands the pressed fill to it', () => {
    const { container } = render(<Harness />);
    const gliders = container.querySelectorAll('.seg-glider');
    expect(gliders).toHaveLength(1);
    expect(gliders[0]?.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelector('.seg')?.hasAttribute('data-glide')).toBe(true);
  });

  it('keeps radio-group semantics while the marker moves', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Week' }));
    expect(screen.getByRole('button', { name: 'Week' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Day' }).getAttribute('aria-pressed')).toBe('false');
  });
});
