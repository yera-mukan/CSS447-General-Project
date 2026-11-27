import type { Library, Page } from "./types"
export const apiBase = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "")
export class Unauthorized extends Error {}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiBase + path, { ...init, credentials: "include", headers: {Accept: "application/json", ...init?.headers} })
  if (response.status === 401) throw new Unauthorized("Sign in to open your library.")
  if (!response.ok) throw new Error("The library request failed (" + response.status + "). Please try again.")
  if (response.status === 204) return undefined as T
  return response.json()
}
const json = (method: string, data: unknown): RequestInit => ({method, headers: {"Content-Type":"application/json"}, body: JSON.stringify(data)})
export const auth = {
  session: () => request<{email:string}>("/session"),
  signIn: (email: string, password: string) => request<{email:string}>("/session", json("POST", {email,password})),
  register: (email: string, password: string) => request<{email:string}>("/accounts", json("POST", {email,password})),
  signOut: () => request<void>("/session", {method:"DELETE"}),
}
const path = (id: string) => "/documents/" + encodeURIComponent(id)
export const remote: Library = {
  list: (query = "") => request<Page[]>("/documents?q=" + encodeURIComponent(query)),
  upload(file, title) {
    const form = new FormData()
    form.append("file", file)
    form.append("title", title)
    return request<Page>("/documents", {method: "POST", body: form})
  },
  update: (id, changes) => request<void>(path(id), json("PATCH", changes)),
  remove: id => request<void>(path(id), {method: "DELETE"}),
  retry: id => request<void>(path(id) + "/retry", {method: "POST"}),
  async image(page) {
    const response = await fetch(apiBase + path(page.id) + "/image", {credentials: "include"})
    if (response.status === 401) throw new Unauthorized("Your session expired.")
    if (!response.ok) throw new Error("Could not load the original image.")
    return response.blob()
  },
}
