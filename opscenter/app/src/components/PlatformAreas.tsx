// The Platform areas rollup (issue 308, item 24): one row per area with its status, counts and the owner the consumer names. It sits above the
// Operations cards and reads the same list as the rail badge, so a count here is never different from a count there. It reads and shows only.
// The decisions live in lib/platformAreas.ts so a test can load them without the browser.

import { Pill } from '@kit'
import type { StatusTone } from '@kit'
import type { PlatformArea } from '../lib/platformAreas'
import { ownerLine, rollupLine, statusWord } from '../lib/platformAreas'
import './PlatformAreas.css'

const TONE: Record<string, StatusTone> = { needs_me: 'danger', worth_a_look: 'warning', healthy: 'success' }

export default function PlatformAreas({ rows }: { rows: readonly PlatformArea[] }) {
  return (
    <section className="pa" aria-label="Platform areas">
      <p className="pa-sum">{rollupLine(rows)}</p>
      <table className="pa-table">
        <thead>
          <tr>
            <th scope="col">Area</th>
            <th scope="col">Status</th>
            <th scope="col">Owner</th>
            <th scope="col" className="pa-num">
              Problem lines
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.section}>
              <th scope="row">{a.label}</th>
              <td>
                <Pill tone={TONE[a.status] ?? 'neutral'}>{statusWord(a.status)}</Pill>
              </td>
              <td className={a.owner ? '' : 'muted'}>{ownerLine(a)}</td>
              <td className="pa-num">{a.lines}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
