import type {
  Application,
  DeleteResult,
  DisconnectResult,
  ApplicationDetail,
  ApplicationPage,
  ApplicationPatch,
  FieldError,
  FollowUp,
  FollowUpFilter,
  Preview,
  Sequence,
  Settings,
  SequenceInput,
  SequencePatch,
  Tone,
  ListParams,
  StatusEvent,
} from './schemas'

export interface DataSource {
  readonly kind: 'api' | 'demo'
  listApplications(params: ListParams): Promise<ApplicationPage>
  getApplication(id: string): Promise<ApplicationDetail>
  listEvents(id: string): Promise<StatusEvent[]>
  updateApplication(id: string, patch: ApplicationPatch): Promise<ApplicationDetail>
  listFollowUps(state?: FollowUpFilter): Promise<FollowUp[]>
  skipFollowUp(id: string): Promise<FollowUp>
  delayFollowUp(id: string, days: number): Promise<FollowUp>
  listSequences(): Promise<Sequence[]>
  createSequence(input: SequenceInput): Promise<Sequence>
  updateSequence(id: string, patch: SequencePatch): Promise<Sequence>
  previewTemplate(template: string, tone: Tone): Promise<Preview>
  getSettings(): Promise<Settings>
  updateSettings(patch: Settings): Promise<Settings>
  disconnectGmail(): Promise<DisconnectResult>
  deleteAccount(): Promise<DeleteResult>
}

export type { Application }

export class ApiError extends Error {
  readonly status: number
  readonly fieldErrors: FieldError[]
  constructor(status: number, message: string, fieldErrors: FieldError[] = []) {
    super(message)
    this.fieldErrors = fieldErrors
    this.name = 'ApiError'
    this.status = status
  }
}
