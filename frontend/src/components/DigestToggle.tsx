import { useDataSource } from '../data/context'
import { useSettings, useUpdateSettings } from '../data/hooks'

export function DigestToggle() {
  const demo = useDataSource().kind === 'demo'
  const settings = useSettings()
  const update = useUpdateSettings()
  return (
    <section className="mt-6" aria-labelledby="digest-heading">
      <h2 id="digest-heading" className="text-lg font-semibold">
        Email
      </h2>
      <label className="mt-2 flex items-center gap-2">
        <input
          type="checkbox"
          checked={settings.data?.digest_enabled ?? false}
          disabled={demo || settings.data === undefined}
          onChange={(event) => update.mutate({ digest_enabled: event.target.checked })}
        />
        Daily digest
      </label>
      <p className="mt-1 text-sm">
        A short email once a day (around 7 to 8 am Toronto time) with company names and statuses
        only. Nothing is sent on quiet days.
      </p>
      {demo && <p className="mt-1 text-sm">Digest settings are not available in the demo.</p>}
      {update.isError && (
        <p role="alert" className="mt-1 text-sm text-red-800 dark:text-red-300">
          Could not save. Your setting was not changed.
        </p>
      )}
    </section>
  )
}
