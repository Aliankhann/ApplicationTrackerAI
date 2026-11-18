import { useState } from 'react'
import { ErrorState, LoadingSkeleton } from '../components/QueryStates'
import { ApiError } from '../data/dataSource'
import { usePreview, useSequences, useUpdateSequence } from '../data/hooks'
import { TONES, type FieldError, type Sequence, type Tone } from '../data/schemas'
import { MAX_STEPS, PLACEHOLDERS, validateSteps } from '../data/sequenceValidation'

interface StepDraft {
  delay_days: string
  template: string
  max_attempts: string
}

const toDraft = (s: Sequence['steps'][number]): StepDraft => ({
  delay_days: String(s.delay_days),
  template: s.template,
  max_attempts: String(s.max_attempts),
})
const toStep = (d: StepDraft) => ({
  delay_days: d.delay_days.trim() === '' ? NaN : Number(d.delay_days),
  template: d.template.replace(/\r\n/g, '\n'),
  max_attempts: d.max_attempts.trim() === '' ? NaN : Number(d.max_attempts),
})

function Msg({ id, errors }: { id: string; errors: Record<string, string> }) {
  const text = errors[id]
  return text ? (
    <p id={`${id}-error`} className="text-sm text-red-800 dark:text-red-300">
      {text}
    </p>
  ) : null
}

function Preview({ template, tone, label }: { template: string; tone: Tone; label: string }) {
  const preview = usePreview(template, tone)
  return (
    <div
      aria-label={`${label} preview`}
      className="mt-2 rounded bg-gray-100 p-2 text-sm dark:bg-gray-800"
    >
      {preview.isSuccess ? (
        <pre className="whitespace-pre-wrap font-sans">{preview.data.text}</pre>
      ) : (
        <p>
          {preview.isError ? 'Preview unavailable until the template is valid.' : 'Loading preview'}
        </p>
      )}
    </div>
  )
}

function StepEditor(props: {
  index: number
  draft: StepDraft
  tone: Tone
  errors: Record<string, string>
  canRemove: boolean
  onChange: (next: StepDraft) => void
  onRemove: () => void
}) {
  const { index, draft, tone, errors, onChange } = props
  const n = index + 1
  const key = (name: string) => `steps.${index}.${name}`
  return (
    <fieldset className="rounded border p-3">
      <legend className="px-1 font-medium">Step {n}</legend>
      <div className="flex flex-wrap gap-4">
        <label className="text-sm">
          Delay (days) for step {n}
          <input
            className="field ml-2 w-20"
            type="number"
            value={draft.delay_days}
            onChange={(e) => onChange({ ...draft, delay_days: e.target.value })}
          />
        </label>
        <label className="text-sm">
          Max attempts for step {n}
          <input
            className="field ml-2 w-20"
            type="number"
            value={draft.max_attempts}
            onChange={(e) => onChange({ ...draft, max_attempts: e.target.value })}
          />
        </label>
      </div>
      <Msg id={key('delay_days')} errors={errors} />
      <Msg id={key('max_attempts')} errors={errors} />
      <label className="mt-2 block text-sm">
        Template for step {n}
        <textarea
          className="field mt-1 block w-full"
          rows={4}
          value={draft.template}
          onChange={(e) => onChange({ ...draft, template: e.target.value })}
        />
      </label>
      <Msg id={key('template')} errors={errors} />
      <Preview template={draft.template} tone={tone} label={`Step ${n}`} />
      {props.canRemove && (
        <button type="button" className="btn mt-2" onClick={props.onRemove}>
          Remove step {n}
        </button>
      )}
    </fieldset>
  )
}

const errorMap = (errors: FieldError[]) =>
  Object.fromEntries([...errors].reverse().map((e) => [e.field, e.message]))

function Editor({ sequence }: { sequence: Sequence }) {
  const update = useUpdateSequence(sequence.id)
  const [steps, setSteps] = useState(() => sequence.steps.map(toDraft))
  const [tone, setTone] = useState<Tone>(sequence.tone)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState(false)

  const change = (i: number, next: StepDraft) => {
    setSaved(false)
    setSteps((all) => all.map((s, j) => (j === i ? next : s)))
  }

  const save = () => {
    const parsed = steps.map(toStep)
    const clientErrors = validateSteps(parsed)
    setErrors(errorMap(clientErrors))
    setSaved(false)
    if (clientErrors.length > 0) return
    update.mutate(
      { steps: parsed, tone },
      {
        onSuccess: () => setSaved(true),
        onError: (error) => {
          const fields = error instanceof ApiError ? error.fieldErrors : []
          setErrors(
            fields.length > 0 ? errorMap(fields) : { form: 'Could not save. Please try again.' },
          )
        },
      },
    )
  }

  return (
    <form
      className="mt-4 space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      <label className="block text-sm">
        Tone
        <select
          className="field ml-2"
          value={tone}
          onChange={(e) => setTone(e.target.value as Tone)}
        >
          {TONES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      <Msg id="tone" errors={errors} />
      <p className="text-sm text-gray-700 dark:text-gray-300">
        Placeholders you can use: {PLACEHOLDERS.map((p) => `{${p}}`).join(', ')}. Missing values
        fall back to safe text. Delays count days since you applied and must increase.
      </p>
      <Msg id="steps" errors={errors} />
      {steps.map((draft, i) => (
        <StepEditor
          key={i}
          index={i}
          draft={draft}
          tone={tone}
          errors={errors}
          canRemove={steps.length > 1}
          onChange={(next) => change(i, next)}
          onRemove={() => setSteps((all) => all.filter((_, j) => j !== i))}
        />
      ))}
      <button
        type="button"
        className="btn"
        disabled={steps.length >= MAX_STEPS}
        onClick={() =>
          setSteps((all) => [
            ...all,
            {
              delay_days: String(Number(all.at(-1)?.delay_days || 0) + 7),
              template: 'I wanted to follow up on the {role} role at {company}.',
              max_attempts: '1',
            },
          ])
        }
      >
        Add step
      </button>
      <Msg id="form" errors={errors} />
      <div className="flex items-center gap-3">
        <button type="submit" className="btn btn-on" disabled={update.isPending}>
          {update.isPending ? 'Saving' : 'Save'}
        </button>
        {saved && <span role="status">Saved</span>}
      </div>
    </form>
  )
}

export default function FollowUpSettingsPage() {
  const query = useSequences()
  const sequence = query.data?.find((s) => s.is_default)
  return (
    <main className="mx-auto max-w-3xl p-4">
      <h1 className="text-2xl font-bold">Follow-up settings</h1>
      {query.isPending && <LoadingSkeleton label="Loading sequence" />}
      {query.isError && (
        <ErrorState message="Could not load your sequence." onRetry={() => void query.refetch()} />
      )}
      {sequence && <Editor key={sequence.id} sequence={sequence} />}
    </main>
  )
}
