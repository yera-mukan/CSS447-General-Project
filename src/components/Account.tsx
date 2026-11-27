import { useState, type FormEvent } from "react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { auth, Unauthorized } from "@/lib/api"
import { errorText } from "@/lib/types"
type Props = { signedIn: (email: string) => void; initialMode?: "login" | "register" }
export function AccountAccess({ signedIn, initialMode = "login" }: Props) {
  const mode = initialMode
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!import.meta.env.VITE_API_BASE_URL) { setError("Account access requires a connected library server."); return }
    const data = new FormData(event.currentTarget)
    const email = String(data.get("email")).trim()
    const password = String(data.get("password"))
    const confirmation = String(data.get("confirmation") || "")
    if (mode === "register" && password !== confirmation) {
      setError("Those passwords don’t match.")
      return
    }
    setError("")
    setBusy(true)
    try {
      const session = mode === "register"
        ? await auth.register(email, password)
        : await auth.signIn(email, password)
      signedIn(session.email)
    } catch (reason) {
      if (reason instanceof Unauthorized) setError(mode === "login" ? "Check your email and password." : "An account with this email may already exist.")
      else setError(errorText(reason))
    } finally { setBusy(false) }
  }
  const registering = mode === "register"
  return <main className="sign-in"><img src="/icon.svg" width="42" alt=""/><h1>{registering ? "Create your account" : "Welcome back"}</h1>
    <p>{registering ? "Keep your pages together in a private library." : "Sign in to open your document library."}</p>
    <form className="form-stack" onSubmit={submit}>
      <label>Email<Input type="email" name="email" autoComplete="email" required maxLength={254}/></label>
      <label>Password<Input type="password" name="password" autoComplete={registering ? "new-password" : "current-password"} minLength={8} required/></label>
      {registering && <label>Confirm password<Input type="password" name="confirmation" autoComplete="new-password" minLength={8} required/></label>}
      {error && <p role="alert" className="error">{error}</p>}
      <Button disabled={busy}>{busy ? "Please wait…" : registering ? "Create account" : "Sign in"}</Button>
    </form>
    <p className="account-switch">{registering ? "Already have an account?" : "Don’t have an account?"} <a href={registering ? "/login" : "/register"}>{registering ? "Sign in" : "Create an account"}</a></p><a href="/">Back to library</a>
  </main>
}
export const SignIn = AccountAccess
