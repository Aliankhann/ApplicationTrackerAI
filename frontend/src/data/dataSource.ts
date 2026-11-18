import type {
  Application,
  ApplicationDetail,
  ApplicationPage,
  ApplicationPatch,
  ListParams,
  StatusEvent,
} from './schemas'

export interface DataSource {
  readonly kind: 'api' | 'demo'
  listApplications(params: ListParams): Promise<ApplicationPage>
  getApplication(id: string): Promise<ApplicationDetail>
  listEvents(id: string): Promise<StatusEvent[]>
  updateApplication(id: string, patch: ApplicationPatch): Promise<ApplicationDetail>
}

export type { Application }

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
