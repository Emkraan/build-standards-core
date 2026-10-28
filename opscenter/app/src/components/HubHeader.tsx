// The title block of a hub page: the kit PageHeader (eyebrow, title, one-line purpose, status
// only, no actions per web-ui.md rule 6) with the hub's route tabs under it.
import { PageHeader } from '@kit'
import type { ReactNode } from 'react'
import type { TabDef } from './Tabs'
import { Tabs } from './Tabs'

export function HubHeader({
  eyebrow,
  title,
  subtitle,
  status,
  tabs,
}: {
  eyebrow?: string
  title: string
  subtitle?: string
  status?: ReactNode
  tabs?: TabDef[]
}) {
  return (
    <div className="hub-head">
      <PageHeader eyebrow={eyebrow} title={title} subtitle={subtitle} status={status} />
      {tabs && <Tabs tabs={tabs} label={`${title} sections`} />}
    </div>
  )
}
