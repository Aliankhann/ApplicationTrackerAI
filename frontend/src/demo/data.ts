import type { ApplicationDetail, Status, StatusEvent } from '../data/schemas'

// Synthetic data only: invented companies, no real email. Dates are offsets (days before "now").
interface Seed {
  company: string | null
  role: string | null
  status: Status
  ghosted?: boolean
  appliedDaysAgo: number | null
  lastDaysAgo: number
  needsReview?: boolean
  paused?: boolean
  subject: string
  snippet: string
  path: Status[]
}

const SEEDS: Seed[] = [
  {
    company: 'Northwind Labs',
    role: 'Software Engineering Intern',
    status: 'applied',
    appliedDaysAgo: 2,
    lastDaysAgo: 2,
    subject: 'Thanks for applying to Northwind Labs',
    snippet: 'We received your application and will review it shortly.',
    path: ['applied'],
  },
  {
    company: 'Brightpine Analytics',
    role: 'Data Science Intern',
    status: 'applied',
    appliedDaysAgo: 4,
    lastDaysAgo: 4,
    subject: 'Application received',
    snippet: 'Thank you for your interest in the Data Science internship.',
    path: ['applied'],
  },
  {
    company: 'Quillfeather Systems',
    role: 'Backend Intern',
    status: 'applied',
    appliedDaysAgo: 6,
    lastDaysAgo: 6,
    paused: true,
    subject: 'We got your application',
    snippet: 'Our team reads every application carefully.',
    path: ['applied'],
  },
  {
    company: 'Harbor & Vale',
    role: 'Product Engineering Intern',
    status: 'applied',
    ghosted: true,
    appliedDaysAgo: 45,
    lastDaysAgo: 45,
    subject: 'Your application to Harbor & Vale',
    snippet: 'Thanks for applying. We will be in touch.',
    path: ['applied'],
  },
  {
    company: 'Lumenfield',
    role: 'Frontend Intern',
    status: 'applied',
    ghosted: true,
    appliedDaysAgo: 38,
    lastDaysAgo: 38,
    subject: 'Application confirmation',
    snippet: 'Your application has been submitted.',
    path: ['applied'],
  },
  {
    company: 'Copperleaf Robotics',
    role: 'Embedded Software Intern',
    status: 'applied',
    ghosted: true,
    appliedDaysAgo: 60,
    lastDaysAgo: 60,
    subject: 'Thanks for your interest',
    snippet: 'We have received your resume.',
    path: ['applied'],
  },
  {
    company: 'Meridian Cloud',
    role: 'Platform Engineering Intern',
    status: 'online_assessment',
    appliedDaysAgo: 12,
    lastDaysAgo: 3,
    subject: 'Next step: online assessment',
    snippet: 'Please complete the coding assessment within 7 days.',
    path: ['applied', 'online_assessment'],
  },
  {
    company: 'Tidewater Games',
    role: 'Gameplay Programmer Intern',
    status: 'online_assessment',
    appliedDaysAgo: 15,
    lastDaysAgo: 5,
    subject: 'Your assessment link',
    snippet: 'Use the link below to start your timed challenge.',
    path: ['applied', 'online_assessment'],
  },
  {
    company: 'Ashgrove Health',
    role: 'Machine Learning Intern',
    status: 'interview',
    appliedDaysAgo: 25,
    lastDaysAgo: 1,
    subject: 'Interview scheduling',
    snippet: 'We would like to invite you to a 45 minute technical interview.',
    path: ['applied', 'online_assessment', 'interview'],
  },
  {
    company: 'Fernhill Payments',
    role: 'Security Engineering Intern',
    status: 'interview',
    appliedDaysAgo: 30,
    lastDaysAgo: 7,
    subject: 'Interview confirmation',
    snippet: 'Your interview is confirmed. Please review the agenda.',
    path: ['applied', 'interview'],
  },
  {
    company: 'Saltmarsh Media',
    role: 'Mobile Developer Intern',
    status: 'interview',
    appliedDaysAgo: 28,
    lastDaysAgo: 9,
    needsReview: true,
    subject: 'Let us find a time to chat',
    snippet: 'Are you free for a quick call next week?',
    path: ['applied', 'interview'],
  },
  {
    company: 'Ironbridge Logistics',
    role: 'Software Engineer Intern',
    status: 'offer',
    appliedDaysAgo: 50,
    lastDaysAgo: 2,
    subject: 'Offer of internship',
    snippet: 'We are delighted to offer you a summer internship position.',
    path: ['applied', 'online_assessment', 'interview', 'offer'],
  },
  {
    company: 'Willowbrook Energy',
    role: 'Data Engineering Intern',
    status: 'offer',
    appliedDaysAgo: 41,
    lastDaysAgo: 10,
    subject: 'Your offer details',
    snippet: 'Congratulations! Details of your offer are below.',
    path: ['applied', 'interview', 'offer'],
  },
  {
    company: 'Cinderhall Studios',
    role: 'Graphics Intern',
    status: 'rejected',
    appliedDaysAgo: 35,
    lastDaysAgo: 14,
    subject: 'Update on your application',
    snippet: 'After careful consideration we will not be moving forward.',
    path: ['applied', 'rejected'],
  },
  {
    company: 'Oakmont Robotics',
    role: 'Controls Software Intern',
    status: 'rejected',
    appliedDaysAgo: 40,
    lastDaysAgo: 20,
    subject: 'Your application status',
    snippet: 'Unfortunately we have decided to pursue other candidates.',
    path: ['applied', 'interview', 'rejected'],
  },
  {
    company: null,
    role: null,
    status: 'applied',
    appliedDaysAgo: null,
    lastDaysAgo: 0,
    needsReview: true,
    subject: 'Re: your recent application',
    snippet: 'Thanks for reaching out about the role.',
    path: ['applied'],
  },
  {
    company: 'Pebblecreek Software',
    role: null,
    status: 'online_assessment',
    appliedDaysAgo: 9,
    lastDaysAgo: 2,
    needsReview: true,
    subject: 'Assessment invitation',
    snippet: 'Complete the skills assessment at your convenience.',
    path: ['applied', 'online_assessment'],
  },
  {
    company: 'Driftwood Security',
    role: 'Security Analyst Intern',
    status: 'applied',
    appliedDaysAgo: 8,
    lastDaysAgo: 8,
    needsReview: true,
    subject: 'Application update',
    snippet: 'We are still reviewing applications for this role.',
    path: ['applied'],
  },
]

const DAY_MS = 86_400_000
const iso = (now: Date, daysAgo: number) => new Date(now.getTime() - daysAgo * DAY_MS).toISOString()
const idFor = (index: number) => `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`

function buildEvents(seed: Seed, now: Date): StatusEvent[] {
  const start = seed.appliedDaysAgo ?? seed.lastDaysAgo
  const steps = seed.path.length
  return seed.path.map((to, i) => {
    const daysAgo = steps === 1 ? start : start - ((start - seed.lastDaysAgo) * i) / (steps - 1)
    return {
      from_status: i === 0 ? null : (seed.path[i - 1] ?? null),
      to_status: to,
      reason: i === 0 ? 'created' : 'classifier:demo-rule',
      at: iso(now, daysAgo),
    }
  })
}

export interface DemoRecord {
  detail: ApplicationDetail
  events: StatusEvent[]
}

export function buildDemoRecords(now: Date = new Date()): DemoRecord[] {
  return SEEDS.map((seed, index) => ({
    detail: {
      id: idFor(index),
      company: seed.company,
      role: seed.role,
      status: seed.status,
      display_status: seed.ghosted ? 'ghosted' : seed.status,
      applied_at: seed.appliedDaysAgo === null ? null : iso(now, seed.appliedDaysAgo),
      last_activity_at: iso(now, seed.lastDaysAgo),
      status_locked: false,
      needs_review: seed.needsReview ?? false,
      followups_paused: seed.paused ?? false,
      subject: seed.subject,
      snippet: seed.snippet,
    },
    events: buildEvents(seed, now),
  }))
}
