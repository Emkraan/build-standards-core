// Date: 2026-11-25
// Purpose: the table spec (issue 327, section 5) as data, shared by the source test (tableColumns.test.mjs) and the rendered test
// (renderedTables.test.mjs), so the two cannot disagree about what the spec says.
// Each entry names the page route and the API the page needs, so the rendered test knows where to look.

// A width is a px or percent string the column declares, or FLEX when the column takes what is left (the spec's number for it is the
// measured result at 1208px, not a declared value).
export const FLEX = 'flex'

export const SPEC = [
  {
    table: 'Action Center table',
    file: 'components/ActionTable.tsx',
    columns: [
      ['Priority', '104px'],
      ['Item', FLEX],
      ['Person', '112px'],
      ['Source', '112px'],
      ['1:1 / status', '124px'],
      ['Tickets', '160px'],
      ['Since', '108px'],
    ],
  },
  {
    table: 'Routing, considered',
    file: 'pages/ActionRouting.tsx',
    columns: [
      ['Input', '42%'],
      ['What happened', '58%'],
    ],
  },
  {
    table: 'Backlog',
    file: 'pages/Backlog.tsx',
    columns: [
      ['Key', '140px'],
      ['Summary', FLEX],
      ['Priority', '108px'],
      ['Status', '170px'],
      ['Type', '96px'],
      ['Pts', '64px'],
      ['Actions', '310px'],
    ],
  },
  {
    table: 'Spend, token windows',
    file: 'pages/infra/Spend.tsx',
    columns: [
      ['Window', FLEX],
      ['Calls', FLEX],
      ['Input', FLEX],
      ['Output', FLEX],
      ['Cache read', FLEX],
      ['Cache write', FLEX],
      ['Total', FLEX],
    ],
  },
  {
    table: 'Spend, by cron job',
    file: 'pages/infra/Spend.tsx',
    columns: [
      ['Job', FLEX],
      ['Runs', FLEX],
      ['Fell back', FLEX],
      ['Billed today', FLEX],
      ['Billed 7d', FLEX],
      ['Team 7d', FLEX],
    ],
  },
  {
    table: 'Spend, by month',
    file: 'pages/infra/Spend.tsx',
    columns: [
      ['Month', FLEX],
      ['Billed', FLEX],
      ['Team', FLEX],
      ['Unattrib.', FLEX],
      ['List total', FLEX],
    ],
  },
  {
    table: 'Debt and improvements',
    file: 'pages/EngBacklog.tsx',
    columns: [
      ['Id', '120px'],
      ['Item', FLEX],
      ['Severity or goal / effort', '240px'],
      ['Status', '140px'],
      ['Date', '96px'],
    ],
  },
  {
    table: 'Team, throughput by sprint',
    file: 'pages/TeamPerformance.tsx',
    columns: [
      ['Sprint', '223px'],
      ['Done', '188px'],
      ['Points', '216px'],
    ],
  },
  {
    table: 'Team, open items',
    file: 'pages/TeamPerformance.tsx',
    columns: [
      ['Key', '120px'],
      ['Status', '140px'],
      ['Priority', '110px'],
      ['Summary', FLEX],
    ],
  },
  {
    table: 'Team, run ledger',
    file: 'pages/TeamHistory.tsx',
    columns: [
      ['Period', '152px'],
      ['Sprints', '208px'],
      ['Engineer', '201px'],
      ['Completion', '153px'],
      ['Pts deliv.', '133px'],
      ['Done', '101px'],
      ['Carry', '103px'],
      ['Intake', '110px'],
    ],
  },
]

// Tables the app draws as a plain table element, matched on the heading cells. The spec shows the headings in capitals, a style rule.
export const HEAD_SPEC = [{ table: 'Reviews, grants', file: 'components/ApprovalBrief.tsx', marker: 'rh-grants rh-grants-why', headings: ['Kind', 'What', 'Severity', 'Where'] }]

export const DRIFT = [
  {
    table: 'Scheduled jobs',
    file: 'pages/infra/Jobs.tsx',
    columns: [
      ['Job', FLEX],
      ['Type', '117px'],
      ['Schedule', '133px'],
      ['Last run', '88px'],
      ['Next', '78px'],
      ['Logs 7d', '86px'],
      ['Health', '103px'],
    ],
    why: 'the table adds an unlabelled row action column after Health that the spec does not list',
  },
  {
    table: 'Changes',
    file: 'components/Approvals.tsx',
    columns: [
      ['Change', '120px'],
      ['Summary', FLEX],
      ['Window', '150px'],
      ['Risk', '120px'],
      ['Type and status', '220px'],
      ['', '90px'],
    ],
    why: 'the table has no Type and status column and labels the last column Actions instead of leaving it unlabelled',
  },
  {
    table: 'Reviews, workflow runs',
    file: 'components/TfReviews.tsx',
    columns: [
      ['When', FLEX],
      ['PR', FLEX],
      ['Workflow', FLEX],
      ['Files', FLEX],
    ],
    why: 'the first heading reads When (UTC), the spec reads When',
  },
]
