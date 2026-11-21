// The title block of a hub page: the kit PageHeader (eyebrow, title, one-line purpose, status
// only, no actions per the web-ui-standard doc) with the hub's route tabs under it.
import { PageHeader } from '@kit'
import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { navFor } from '../shell/nav'
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
  // The chip is the rail icon of the page that owns the route, so the header and the rail always agree.
  const icon = navFor(useLocation().pathname)?.icon
  return (
    <div className="hub-head">
      <PageHeader eyebrow={eyebrow} title={title} subtitle={subtitle} status={status} icon={icon} />
      {tabs && <Tabs tabs={tabs} label={`${title} sections`} />}
    </div>
  )
}
