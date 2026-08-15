import Link from "next/link";
import { DEFAULT_API_BASE_URL } from "@rebirth/api-client";

export default function Home() {
  return (
    <>
      <section className="panel">
        <h1 className="title">Console Waterfall</h1>
        <p className="subtitle">
          Interface de pilotage pour auth, utilisateurs et projets MS Project.
        </p>
        <div className="row" style={{ marginTop: "1rem" }}>
          <span className="tag">API</span>
          <strong>{DEFAULT_API_BASE_URL}</strong>
        </div>
      </section>

      <section className="panel">
        <div className="grid-3">
          <article>
            <h2 className="title" style={{ fontSize: "1.2rem" }}>
              Login
            </h2>
            <p className="subtitle">Authentification JWT avec refresh token.</p>
            <div className="row" style={{ marginTop: "0.8rem" }}>
              <Link href="/login" className="btn btn-primary">
                Ouvrir
              </Link>
            </div>
          </article>
          <article>
            <h2 className="title" style={{ fontSize: "1.2rem" }}>
              Utilisateurs
            </h2>
            <p className="subtitle">Administration des comptes et des droits.</p>
            <div className="row" style={{ marginTop: "0.8rem" }}>
              <Link href="/users" className="btn">
                Gérer
              </Link>
            </div>
          </article>
          <article>
            <h2 className="title" style={{ fontSize: "1.2rem" }}>
              Projets
            </h2>
            <p className="subtitle">Lecture des projets et édition des descriptions tâches.</p>
            <div className="row" style={{ marginTop: "0.8rem" }}>
              <Link href="/projects" className="btn">
                Parcourir
              </Link>
            </div>
          </article>
        </div>
      </section>
    </>
  );
}
