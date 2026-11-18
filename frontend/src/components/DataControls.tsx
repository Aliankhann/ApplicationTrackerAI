import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { GOOGLE_PERMISSIONS_URL } from '../constants'
import { useDataSource } from '../data/context'
import { ApiError } from '../data/dataSource'
import { useDeleteAccount, useDisconnectGmail } from '../data/hooks'
import { Dialog } from './Dialog'

const CONFIRM_WORD = 'DELETE'

export function RemoveAccessLink() {
  return (
    <a href={GOOGLE_PERMISSIONS_URL} target="_blank" rel="noopener noreferrer" className="link">
      Remove access in your Google Account
    </a>
  )
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return 'A sync is running right now. Try again in a moment.'
  }
  if (error instanceof ApiError && error.status === 503) {
    return 'Google could not be reached to revoke access, so nothing was changed. Try again later.'
  }
  return 'Something went wrong. Nothing was confirmed; please try again.'
}

function DisconnectDialog({
  onClose,
  onDone,
}: {
  onClose: () => void
  onDone: (revokedAtGoogle: boolean | null) => void
}) {
  const disconnect = useDisconnectGmail()
  return (
    <Dialog title="Disconnect Gmail?" onClose={onClose}>
      <p className="mt-2 text-sm">
        We revoke our access to your Gmail at Google and delete the email data we synced: thread
        subjects and snippets. Your applications stay, but lose their email details. Follow-ups that
        have not been drafted are cancelled.
      </p>
      {disconnect.isError && (
        <p role="alert" className="mt-3 text-sm text-red-800 dark:text-red-300">
          {errorMessage(disconnect.error)}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          disabled={disconnect.isPending}
          onClick={() =>
            disconnect.mutate(undefined, {
              onSuccess: (result) => {
                onDone(result.revoked_at_google)
                onClose()
              },
            })
          }
        >
          Disconnect Gmail and delete synced data
        </button>
      </div>
    </Dialog>
  )
}

function DeleteDialog({ onClose }: { onClose: () => void }) {
  const [typed, setTyped] = useState('')
  const remove = useDeleteAccount()
  const navigate = useNavigate()
  const confirm = () =>
    remove.mutate(undefined, {
      onSuccess: (result) =>
        void navigate('/goodbye', {
          state: { revokedAtGoogle: result.revoked_at_google },
        }),
    })
  return (
    <Dialog title="Delete your account and data?" onClose={onClose}>
      <p className="mt-2 text-sm">
        This permanently deletes your account, applications, follow-ups, settings, and synced email
        data, and revokes our access to your Gmail. It cannot be undone.
      </p>
      <label className="mt-3 block text-sm">
        Type {CONFIRM_WORD} to confirm
        <input
          className="mt-1 block w-full rounded border px-2 py-1"
          value={typed}
          autoComplete="off"
          onChange={(e) => setTyped(e.target.value)}
        />
      </label>
      {remove.isError && (
        <p role="alert" className="mt-3 text-sm text-red-800 dark:text-red-300">
          {errorMessage(remove.error)}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn"
          disabled={typed !== CONFIRM_WORD || remove.isPending}
          onClick={confirm}
        >
          Permanently delete my account and data
        </button>
      </div>
    </Dialog>
  )
}

type Open = 'disconnect' | 'delete' | null

export function DataControls() {
  const demo = useDataSource().kind === 'demo'
  const [open, setOpen] = useState<Open>(null)
  const [disconnected, setDisconnected] = useState<boolean | null | undefined>(undefined)
  const close = () => setOpen(null)
  return (
    <section aria-labelledby="your-data" className="mt-6">
      <h2 id="your-data" className="text-lg font-bold">
        Your data
      </h2>
      {demo && <p className="mt-1 text-sm">Not available in the demo.</p>}
      <div className="mt-3 flex flex-wrap gap-3">
        <button type="button" className="btn" disabled={demo} onClick={() => setOpen('disconnect')}>
          Disconnect Gmail
        </button>
        <button type="button" className="btn" disabled={demo} onClick={() => setOpen('delete')}>
          Delete my account and data
        </button>
      </div>
      {disconnected !== undefined && (
        <div role="status" className="mt-3 text-sm">
          <p>Gmail disconnected and your synced email data was deleted.</p>
          {disconnected === false && (
            <p className="mt-1">
              We could not revoke access at Google. <RemoveAccessLink /> to finish.
            </p>
          )}
        </div>
      )}
      <p className="mt-3 text-sm">
        <Link to="/privacy" className="link">
          How we handle your data
        </Link>
      </p>
      {open === 'disconnect' && <DisconnectDialog onClose={close} onDone={setDisconnected} />}
      {open === 'delete' && <DeleteDialog onClose={close} />}
    </section>
  )
}
