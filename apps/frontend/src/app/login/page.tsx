"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, login } from "@/lib/backend";
import { setSession } from "@/lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@waterfall.local");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      const tokens = await login(email, password);
      setSession({
        accessToken: tokens.access_token,
        refreshToken: tokens.refreshToken,
      });
      router.push("/projects");
    } catch (cause) {
      if (cause instanceof ApiError) {
        setError(cause.message);
      } else {
        setError("Erreur inattendue pendant le login");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" style={{ maxWidth: "530px", margin: "0 auto" }}>
      <h1 className="title">Connexion</h1>
      <p className="subtitle">Accès à la console Waterfall.</p>

      <form onSubmit={onSubmit} style={{ marginTop: "1rem" }}>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            required
          />
        </div>

        <div className="field">
          <label htmlFor="password">Mot de passe</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </div>

        {error ? <p className="error">{error}</p> : null}

        <div className="row" style={{ marginTop: "0.8rem" }}>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Connexion..." : "Se connecter"}
          </button>
        </div>
      </form>
    </section>
  );
}
