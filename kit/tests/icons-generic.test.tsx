/* The nine generic icons: each draws an inline SVG in currentColor, is hidden from assistive
   technology by default and takes a size. */
import { render } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { IconCalendar, IconClock, IconEdit, IconEye, IconEyeOff, IconFolder, IconList, IconMail, IconTrash } from '../src';

const ICONS = { calendar: IconCalendar, clock: IconClock, edit: IconEdit, eye: IconEye, 'eye-off': IconEyeOff, folder: IconFolder, list: IconList, mail: IconMail, trash: IconTrash };

describe('generic icons', () => {
  for (const [name, Icon] of Object.entries(ICONS)) {
    it(`${name} is a decorative currentColor svg`, () => {
      const { container } = render(<Icon />);
      const svg = container.querySelector('svg');
      expect(svg?.getAttribute('data-icon')).toBe(name);
      expect(svg?.getAttribute('aria-hidden')).toBe('true');
      expect(svg?.getAttribute('stroke')).toBe('currentColor');
      expect(svg?.getAttribute('width')).toBe('16');
      expect(svg?.querySelector('path, circle, rect')).not.toBeNull();
    });
  }

  it('takes a size and passes attributes through', () => {
    const { container } = render(<IconClock size={24} data-x="1" />);
    const svg = container.querySelector('svg');
    expect(svg?.getAttribute('width')).toBe('24');
    expect(svg?.getAttribute('data-x')).toBe('1');
  });

  it('has no axe violations inside a labelled button', async () => {
    const { container } = render(
      <div>
        {Object.entries(ICONS).map(([name, Icon]) => (
          <button key={name} type="button" aria-label={name}>
            <Icon />
          </button>
        ))}
      </div>,
    );
    const res = await axe.run(container);
    expect(res.violations).toEqual([]);
  });
});
