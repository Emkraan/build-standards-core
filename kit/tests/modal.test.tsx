import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { Button, Field, Input, Modal } from '../src/index';

function Host() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Edit device</Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Edit device" primaryAction={{ label: 'Save', onClick: () => setOpen(false) }}>
        <Field label="Name">
          <Input defaultValue="Kiosk" />
        </Field>
      </Modal>
    </>
  );
}

describe('Modal', () => {
  it('moves focus in, traps Tab, closes on Escape and restores focus', async () => {
    const user = userEvent.setup();
    render(<Host />);
    const trigger = screen.getByRole('button', { name: 'Edit device' });
    await user.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Edit device' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    const input = screen.getByLabelText('Name');
    expect(document.activeElement).toBe(input);
    expect(document.body.style.overflow).toBe('hidden');

    const close = screen.getByRole('button', { name: 'Close' });
    const save = screen.getByRole('button', { name: 'Save' });
    act(() => save.focus());
    await user.tab();
    expect(document.activeElement).toBe(close);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(save);
    for (let i = 0; i < 6; i += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe('');
  });

  it('only the top dialog answers Escape', async () => {
    const user = userEvent.setup();
    function Stacked() {
      const [outer, setOuter] = useState(true);
      const [inner, setInner] = useState(true);
      return (
        <>
          <Modal open={outer} onClose={() => setOuter(false)} title="Outer" cancelLabel={null}>
            <p>Outer body</p>
          </Modal>
          <Modal open={inner} onClose={() => setInner(false)} title="Inner" cancelLabel={null}>
            <p>Inner body</p>
          </Modal>
        </>
      );
    }
    render(<Stacked />);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Inner' })).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Outer' })).toBeTruthy();
  });
});
