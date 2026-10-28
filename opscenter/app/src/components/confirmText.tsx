// Splits a native-confirm style question into the kit dialog's title (up to the first question
// mark) and body (the rest, line breaks kept), so the wording stays exactly as it was.
import type { ConfirmOptions } from '@kit'

export function confirmText(question: string): Pick<ConfirmOptions, 'title' | 'body'> {
  const i = question.indexOf('?')
  if (i < 0 || i === question.length - 1) return { title: question }
  const rest = question.slice(i + 1).trim()
  return { title: question.slice(0, i + 1), body: rest ? <span className="confirm-body">{rest}</span> : undefined }
}
