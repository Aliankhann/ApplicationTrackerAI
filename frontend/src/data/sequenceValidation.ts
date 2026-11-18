import type { FieldError, Step } from './schemas'

// Mirrors backend/app/services/{sequences,templates}.py. The server stays the authority.
export const PLACEHOLDERS = [
  'recruiter_first_name',
  'role',
  'company',
  'applied_date',
  'your_name',
] as const
export const MAX_STEPS = 5
export const TEMPLATE_MAX = 2000
export const DELAY_MIN = 1
export const DELAY_MAX = 60
export const ATTEMPTS_MAX = 3

const err = (field: string, code: string, message: string): FieldError => ({
  field,
  code,
  message,
})

export function validateTemplate(template: string): string | null {
  if (template.trim().length < 1) return 'Template must not be empty.'
  if (template.length > TEMPLATE_MAX) return `Template must be at most ${TEMPLATE_MAX} characters.`
  if (/[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Zl}\p{Zp}]/u.test(template.replace(/[\n\t]/g, '')))
    return 'Templates may not contain control or invisible characters.'
  if (/<[A-Za-z/!]/.test(template)) return 'Templates are plain text; HTML tags are not allowed.'
  const leftover = template.replace(/\{[a-z_]+\}/g, '')
  if (leftover.includes('{') || leftover.includes('}')) return 'Unbalanced or malformed braces.'
  for (const [, name] of template.matchAll(/\{([a-z_]+)\}/g)) {
    if (!(PLACEHOLDERS as readonly string[]).includes(name!))
      return `Unknown placeholder {${name}}.`
  }
  return null
}

export function validateSteps(steps: Step[]): FieldError[] {
  const errors: FieldError[] = []
  if (steps.length < 1 || steps.length > MAX_STEPS) {
    errors.push(err('steps', 'invalid_count', `Use 1 to ${MAX_STEPS} steps.`))
  }
  steps.forEach((step, i) => {
    const at = `steps.${i}`
    if (
      !Number.isInteger(step.delay_days) ||
      step.delay_days < DELAY_MIN ||
      step.delay_days > DELAY_MAX
    ) {
      errors.push(
        err(
          `${at}.delay_days`,
          'invalid_delay',
          `Delay must be ${DELAY_MIN} to ${DELAY_MAX} days.`,
        ),
      )
    } else if (i > 0 && step.delay_days <= steps[i - 1]!.delay_days) {
      errors.push(
        err(
          `${at}.delay_days`,
          'delays_not_increasing',
          'Delay must be later than the previous step.',
        ),
      )
    }
    const templateError = validateTemplate(step.template)
    if (templateError) errors.push(err(`${at}.template`, 'invalid_template', templateError))
    if (
      !Number.isInteger(step.max_attempts) ||
      step.max_attempts < 1 ||
      step.max_attempts > ATTEMPTS_MAX
    ) {
      errors.push(
        err(`${at}.max_attempts`, 'invalid_attempts', `Attempts must be 1 to ${ATTEMPTS_MAX}.`),
      )
    }
  })
  return errors
}
