// A start button for anything runnable (layout rule 7): opens the kit's run dialog with the safe defaults of the server's
// fixed input spec and says plainly when a run will publish. The server checks every input again and refuses a paused or
// already running item (409); the dialog shows the reason. The button only queues the run.
import { Button, RunDialog, runErrorFrom } from '@kit'
import type { RunInput, RunRequest, RunResult, RunSpec, RunValues } from '@kit'
import { useState } from 'react'
import type { RunAnswer, RunSpecInput } from '../../lib/data'
import { RunError } from '../../lib/data'

export function specOf(inputs: RunSpecInput[] | undefined, ref?: 'main' | 'branch'): RunSpec {
  const list: RunInput[] = (inputs ?? []).map((i) => ({
    name: i.name,
    type: i.type,
    default: i.default,
    ...(i.options ? { options: i.options } : {}),
    ...(i.pattern ? { pattern: i.pattern } : {}),
    ...(i.required ? { required: true } : {}),
    ...(i.help ? { help: i.help } : {}),
  }))
  return ref ? { ref, inputs: list } : { inputs: list }
}

/** True when the values make a run publish: an input with a publishes_when value set to it. */
export function publishesFor(inputs: RunSpecInput[] | undefined) {
  return (values: RunValues) => (inputs ?? []).some((i) => i.publishes_when !== undefined && values[i.name] === i.publishes_when)
}

export interface RunButtonProps {
  label: string
  title: string
  subtitle?: string
  inputs?: RunSpecInput[] | undefined
  ref_?: 'main' | 'branch' | undefined
  /** Why it cannot run now (paused, running): the dialog shows it and keeps the primary button waiting. */
  refusal?: { kind: string; reason: string } | undefined
  start: (request: RunRequest) => Promise<RunAnswer>
  onStarted?: (answer: RunAnswer) => void
  size?: 'sm' | 'md'
  variant?: 'secondary' | 'ghost' | 'primary'
}

export function RunButton({ label, title, subtitle, inputs, ref_, refusal, start, onStarted, size = 'sm', variant = 'secondary' }: RunButtonProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size={size} variant={variant} onClick={() => setOpen(true)}>
        {label}
      </Button>
      <RunDialog
        open={open}
        onClose={() => setOpen(false)}
        title={title}
        subtitle={subtitle}
        spec={specOf(inputs, ref_)}
        publishes={publishesFor(inputs)}
        refusal={refusal}
        onRun={async (request: RunRequest): Promise<RunResult> => {
          try {
            return await start(request)
          } catch (e) {
            if (e instanceof RunError) throw runErrorFrom(e.status, { error: e.message })
            throw e
          }
        }}
        onDone={(r) => onStarted?.(r as RunAnswer)}
      />
    </>
  )
}
