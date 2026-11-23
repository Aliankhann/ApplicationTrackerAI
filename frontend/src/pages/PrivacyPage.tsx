import type { ReactNode } from 'react'
import { Link } from 'react-router'
import {
  CONTACT_MAILTO,
  DEFAULT_INITIAL_SYNC_DAYS,
  GOOGLE_PERMISSIONS_URL,
  PRIVACY_LAST_UPDATED,
} from '../constants'

function Todo({ children }: { children: ReactNode }) {
  return <strong className="font-bold">[TODO: {children}]</strong>
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-8">
      <h2 id={id} className="text-xl font-bold">
        {title}
      </h2>
      <div className="mt-2 space-y-3">{children}</div>
    </section>
  )
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1 pl-6">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  )
}

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-3xl font-bold">Privacy</h1>
      <p className="mt-4">
        This page says what Application Tracker reads, stores, and sends, who can see it, and how to
        delete it. Where something is planned but not built yet, it says so.
      </p>
      <p className="mt-2 text-sm">Last updated: {PRIVACY_LAST_UPDATED}</p>

      <Section id="reads" title="What we read from Gmail">
        <p>
          When you connect Gmail we look at threads from the last {DEFAULT_INITIAL_SYNC_DAYS} days,
          and after that at threads that changed. For each thread we read metadata only: the sender,
          the subject, a short snippet (cut to 200 characters), message dates, and whether the last
          message was yours. We do not read full message bodies.
        </p>
        <p>
          Permissions: <code>gmail.readonly</code> when you connect Gmail. Follow-up drafts need
          <code> gmail.compose</code>, which we ask for only if you turn follow-ups on. That step is
          planned and not built yet.
        </p>
        <p>
          Honest note: <code>gmail.compose</code> technically allows sending mail, not just drafting
          it. The app only ever creates drafts, and that is enforced in our code: the Gmail
          interface the app uses has no send operation. You review and send every draft yourself.
        </p>
      </Section>

      <Section id="stores" title="What we store">
        <p>Per account:</p>
        <Bullets
          items={[
            'Your Google account ID, your email address, and your time zone.',
            'Your Gmail refresh token, encrypted. We never store your Google password.',
            'Your settings, such as whether the daily digest is on, and your follow-up sequences.',
            'Sign-in sessions: a hash of the session token and a hash of your browser’s user-agent string, used only to tell sessions apart. Neither is stored in readable form.',
            'If you were invited by email address, that address is kept with your invite code until you delete your account. The invite code itself is stored only as a hash.',
            'If you sign up with an invite code but do not connect Gmail within 24 hours, your unfinished account is deleted automatically and the code is released.',
            'Sync and digest bookkeeping: timestamps, a Gmail sync checkpoint, and send status, with no email content.',
            'A short activity log: sign-in, sign-out, connecting and disconnecting Gmail, and account deletion, with the time and nothing else.',
          ]}
        />
        <p>Per job-related email thread:</p>
        <Bullets
          items={[
            'The subject, the sender domain (not the full sender address), and a snippet of at most 200 characters.',
            'The first and last message times, the message count, and whether you sent the last message.',
            'How we classified it and why (a label, a confidence, and the rule used).',
          ]}
        />
        <p>Per application:</p>
        <Bullets
          items={[
            'Company and role as we extracted them or as you edited them, the status and its history, and dates.',
            'Follow-up steps, their due dates and states, and the ID of the Gmail draft we created.',
          ]}
        />
        <p>
          Threads that do not look job-related are discarded right away and never written to the
          database. We never store full email bodies, recipient addresses, or the text of drafts.
        </p>
        <p>
          Gmail connection is not live yet in this version, so for now no real Gmail data is being
          read.
        </p>
      </Section>

      <Section id="ai" title="What goes to the AI model">
        <p>
          Currently nothing. Emails are classified by fixed rules that run on our own server. No
          email data is sent to any AI vendor.
        </p>
        <p>
          An AI fallback for emails the rules cannot decide is built and off by default. If it is
          turned on, only the sender domain, subject, and a 200-character snippet of emails the
          rules can't classify are sent to Anthropic's Claude API, and this page will be updated
          first. <Todo>link Anthropic's data terms</Todo>
        </p>
      </Section>

      <Section id="drafts" title="Follow-up drafts and digest emails">
        <p>
          Follow-up drafts are created in your own Gmail, in the original thread, for you to review.
          The recipient address is read from Gmail at the moment a draft is created and is not
          saved.
        </p>
        <p>
          The optional daily digest email lists company names and statuses only. It never contains
          snippets or email text. It has a one-click unsubscribe link, and you can turn it off in
          Settings.
        </p>
      </Section>

      <Section id="access" title="Who can access your data">
        <p>
          Only the operator of this app, who runs it for a small invited group. The operator does
          not browse user data, though they are technically able to read the database. A planned
          admin view will show counts only, never email content. That view is not built yet.
        </p>
        <p>
          Your data is not sold or shared. The services we depend on are Google (Gmail), our hosting
          provider <Todo>hosting provider not yet chosen</Todo>, and an email provider for the
          digest (not yet chosen).
        </p>
      </Section>

      <Section id="security" title="Security">
        <Bullets
          items={[
            'Refresh tokens are encrypted with AES-GCM, and the key is kept outside the database.',
            'Sessions are server-side, in secure HTTP-only cookies, and state-changing requests need a CSRF token.',
            'Every database query on your data is scoped to your account, and automated tests check that one user cannot reach another’s data.',
            'Logs never contain email content or tokens.',
            'Email text is shown as plain text only.',
          ]}
        />
      </Section>

      <Section id="deleting" title="Deleting your data">
        <p>
          <strong>Disconnect Gmail</strong> (Settings): will revoke our access at Google (the Google
          connection is not built yet, so until then Disconnect reports an error and changes
          nothing), and deletes your stored token and all synced email threads, and cancels
          follow-ups that have not been drafted. Your applications stay, without their email
          details, and your account stays.
        </p>
        <p>
          <strong>Delete my account and data</strong> (Settings): deletes every row we hold for you
          in one step and, once the Google connection exists, revokes our access there. A
          confirmation email is planned; sending it is not wired yet. One anonymous record that an
          account was deleted remains, with no user ID or address.
        </p>
        <p>
          If revoking at Google fails, you can remove access yourself at{' '}
          <a
            href={GOOGLE_PERMISSIONS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="link"
          >
            your Google Account permissions
          </a>
          . Drafts already created in your Gmail are yours and stay there until you delete them.
        </p>
        <p>
          Backups: if our host keeps backups, deleted data can remain in them until they age out.{' '}
          <Todo>backup retention window not yet decided</Todo>
        </p>
        <p>
          <Link to="/app/settings" className="link">
            Go to Settings
          </Link>
        </p>
      </Section>

      <Section id="contact" title="Contact">
        <p>
          Questions or requests:{' '}
          <a href={CONTACT_MAILTO} className="link">
            <Todo>contact email not yet decided</Todo>
          </a>
          . Please do not send email content or tokens.
        </p>
      </Section>

      <p className="mt-10">
        <Link to="/" className="link">
          Back home
        </Link>
      </p>
    </main>
  )
}
