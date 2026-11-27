export const statuses = { queued: "Waiting", processing: "Processing", ready: "Ready to review", reviewed: "Reviewed", failed: "Failed" } as const
export type Status = keyof typeof statuses
export type Page = {
  id: string; title: string; filename: string; mime: string; createdAt: string
  status: Status; text: string; starred: boolean; attempts: number
  imageUrl?: string; coverUrl?: string; error?: string
}
export type Changes = Partial<Pick<Page, "starred" | "text" | "title">>
export interface Library {
  list(query?: string): Promise<Page[]>
  upload(file: File, title: string): Promise<Page>
  update(id: string, changes: Changes): Promise<void>
  remove(id: string): Promise<void>
  retry(id: string): Promise<void>
  image(page: Page): Promise<Blob | string>
}
export function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong. Try again."
}
export const maxAttempts = 3
