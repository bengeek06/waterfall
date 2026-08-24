"use client";

import Image from "next/image";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, login } from "@/lib/backend";
import { setSession } from "@/lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);

    try {
      const tokens = await login(email, password);
      setSession({
        accessToken: tokens.access_token,
      });
      router.push("/projects");
    } catch (cause) {
      if (cause instanceof ApiError) {
        toast.error(cause.message);
      } else if (cause instanceof TypeError) {
        toast.error("Backend injoignable (API/CORS). Vérifie que l'API tourne sur http://127.0.0.1:8000.");
      } else {
        toast.error("Erreur inattendue pendant le login");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      <div className="mb-10 flex justify-center">
        <Image src="/waterfall_logo.svg" alt="Waterfall" width={230} height={54} priority />
      </div>
      <Card>
        <CardContent className="p-8">
          <form onSubmit={onSubmit} className="grid gap-6">
            <div className="grid gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="password">Mot de passe</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Connexion..." : "Se connecter"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
