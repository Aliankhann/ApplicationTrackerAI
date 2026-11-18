import type { Tone } from '../data/schemas'

// Mirrors the server's sample context and tone presets; demo mode never calls the API.
const SAMPLE: Record<string, string> = {
  recruiter_first_name: 'Alex',
  role: 'Software Engineering Intern',
  company: 'Example Co',
  applied_date: 'March 3',
  your_name: 'Sam Student',
}
const GREETINGS: Record<Tone, string> = {
  short: 'Hi Alex,',
  warm: "Hi Alex, I hope you're doing well.",
  formal: 'Dear Alex,',
}
const SIGN_OFFS: Record<Tone, string> = {
  short: 'Thanks,',
  warm: 'Best,',
  formal: 'Kind regards,',
}

export function renderPreview(template: string, tone: Tone): string {
  const body = template.replace(/\{([a-z_]+)\}/g, (_m, name: string) => SAMPLE[name] ?? '')
  return `${GREETINGS[tone]}\n\n${body}\n\n${SIGN_OFFS[tone]}\n${SAMPLE.your_name}`
}
