// Copy fallback for when the clipboard API is refused: a kit Modal with the text selected in a
// read-only box, replacing the old native prompt (web-ui.md 0.7). Render `dialog` once.
import { Field, Modal, Textarea } from '@kit'
import { type ReactNode, useCallback, useRef, useState } from 'react'

interface CopyRequest {
  title: string
  text: string
}

export function useCopyDialog(): { showCopy: (title: string, text: string) => void; dialog: ReactNode } {
  const [pending, setPending] = useState<CopyRequest | null>(null)
  const last = useRef<CopyRequest | null>(null)
  if (pending) last.current = pending
  const shown = pending || last.current
  const showCopy = useCallback((title: string, text: string) => setPending({ title, text }), [])
  const dialog = (
    <Modal
      open={pending !== null}
      onClose={() => setPending(null)}
      size="lg"
      title={shown?.title ?? ''}
      subtitle="The clipboard was not available. Select the text below and copy it."
      cancelLabel="Close"
    >
      <Field label="Text to copy">
        <Textarea readOnly rows={10} value={shown?.text ?? ''} data-autofocus="" onFocus={(e) => e.currentTarget.select()} />
      </Field>
    </Modal>
  )
  return { showCopy, dialog }
}
