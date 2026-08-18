export type SessionTokens = {
  accessToken: string;
};

let currentSession: SessionTokens | null = null;

export function getSession(): SessionTokens | null {
  if (typeof window === "undefined") {
    return null;
  }
  return currentSession;
}

export function setSession(tokens: SessionTokens): void {
  if (typeof window === "undefined") {
    return;
  }
  currentSession = tokens;
}

export function clearSession(): void {
  if (typeof window === "undefined") {
    return;
  }
  currentSession = null;
}
