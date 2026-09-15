import { useCallback, useEffect, useState } from "react";
import { Api, type CarBuildResult, type ExecuteResult, type Project, type TractorBuildResult } from "./api";
import { useEventStream } from "./useEventStream";
import STLViewer from "./STLViewer";

const DEMO_SPEC =
  "Je veux concevoir une machine industrielle capable de transporter 500 kg " +
  "a 20 m/min, fonctionnant sous 400 V triphase, avec arret d'urgence, " +
  "capteurs de position, automate programmable et interface operateur.";

const EVENT_COLORS: Record<string, string> = {
  PROJECT_CREATED: "var(--ok)",
  CALCULATION_COMPLETED: "var(--accent)",
  VERIFICATION_PASSED: "var(--ok)",
  VERIFICATION_FAILED: "var(--bad)",
  TASK_FAILED: "var(--bad)",
  TASK_COMPLETED: "var(--text-dim)",
  TASK_STARTED: "var(--text-dim)",
  PLAN_CREATED: "var(--accent)",
  PROJECT_VALIDATED: "var(--ok)",
  SEARCH_COMPLETED: "var(--accent)",
  COMPONENT_SELECTED: "var(--warn)",
};

function outcomeClass(outcome: string): string {
  if (outcome === "PASS") return "badge ok";
  if (outcome === "FAIL") return "badge bad";
  if (outcome === "WARNING") return "badge warn";
  return "badge unknown";
}

function componentBadge(status?: string): string {
  if (status === "SOURCED") return "badge ok";
  if (status === "INSUFFICIENT_SOURCES") return "badge warn";
  return "badge unknown";
}

export default function App() {
  const { events, connected } = useEventStream();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [spec, setSpec] = useState(DEMO_SPEC);
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [tractor, setTractor] = useState<TractorBuildResult | null>(null);
  const [car, setCar] = useState<CarBuildResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  const refreshProjects = useCallback(async () => {
    try {
      setProjects(await Api.listProjects());
    } catch {
      /* backend not started yet */
    }
  }, []);

  // Load history on mount.
  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  const createAndRun = useCallback(async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    setReport(null);
    try {
      const project = await Api.createProject(
        `Console ${new Date().toLocaleTimeString()}`,
        spec.slice(0, 80)
      );
      setProjectId(project.id);
      setTractor(null);
      setCar(null);
      const res = await Api.execute(project.id, spec);
      setResult(res);
      await refreshProjects();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [spec, refreshProjects]);

  const reopenProject = useCallback(async (pid: string) => {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const s = await Api.summary(pid);
      setProjectId(pid);
      setResult(s);
      setTractor(null);
      setCar(null);
      const r = await Api.report(pid);
      setReport(r.content);
      // Reopen stored 3D/electrical builds if the project has any.
      const t = await Api.getTractor(pid);
      if (t) setTractor(t);
      const c = await Api.getCar(pid);
      if (c) setCar(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const buildTractor = useCallback(async () => {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      setTractor(await Api.tractor(projectId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  const buildCar = useCallback(async () => {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      setCar(await Api.car(projectId));
      void refreshProjects();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [projectId, refreshProjects]);

  const loadReport = useCallback(async () => {
    if (!projectId) return;
    try {
      const r = await Api.report(projectId);
      setReport(r.content);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [projectId]);

  const askAI = useCallback(async () => {
    if (!projectId || !question.trim()) return;
    setAsking(true);
    setAnswer(null);
    try {
      const r = await Api.ask(projectId, question.trim());
      setAnswer(r.answer);
      if (r.intent === "design") {
        // The design actually ran: reload the stored build (tractor OR car)
        // so the 3D viewer, plans and deliverables links reflect the new version.
        const t = await Api.getTractor(projectId);
        if (t) setTractor(t);
        const c = await Api.getCar(projectId);
        if (c) setCar(c);
        void refreshProjects();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAsking(false);
    }
  }, [projectId, question, refreshProjects]);

  return (
    <div className="layout">
      <header>
        <h1>AI ENGINEER</h1>
        <span className={connected ? "badge ok" : "badge bad"}>
          {connected ? "WS connecté" : "WS déconnecté"}
        </span>
        <button className="primary" disabled={busy} onClick={createAndRun}>
          {busy ? "Exécution..." : "Nouveau projet + Exécuter"}
        </button>
        {projectId && <small className="dim">Projet : {projectId}</small>}
      </header>

      <main>
        <section className="col">
          <h2>Cahier des charges</h2>
          <textarea value={spec} onChange={(e) => setSpec(e.target.value)} rows={7} />
          {error && <p className="error">Erreur : {error}</p>}

          {result && (
            <>
              <h2>
                Exigences ({result.requirements.length})
                {result.name ? ` — ${result.name}` : ""}
              </h2>
              <ul className="reqs">
                {result.requirements.map((r) => (
                  <li key={r.id}>
                    <code>{r.id}</code> {r.description}
                    {r.raw_value ? ` = ${r.raw_value}` : ""}
                  </li>
                ))}
              </ul>
              {result.known_gaps.length > 0 && (
                <p className="warn">INCONNU (à compléter) : {result.known_gaps.join(", ")}</p>
              )}

              {result.power_w != null && (
                <p>
                  Puissance arbre (déterministe) :{" "}
                  <strong>{result.power_w.toFixed(1)} W</strong>
                </p>
              )}

              <h2>Tâches</h2>
              <table>
                <tbody>
                  {result.tasks.map((t) => (
                    <tr key={t.id}>
                      <td className={t.status === "SUCCESS" ? "ok" : t.status === "FAILED" || t.status === "REQUIRES_REVIEW" ? "bad" : ""}>
                        {t.status}
                      </td>
                      <td>{t.agent}</td>
                      <td>{t.title}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {result.component && (
                <>
                  <h2>Composant recherché (sources web)</h2>
                  <p>
                    <span className={componentBadge(result.component.status)}>
                      {result.component.status}
                    </span>{" "}
                    <strong>{result.component.type}</strong> — {result.component.requirement}
                  </p>
                  <p className="dim">{result.component.note}</p>
                  {result.component.manufacturer_domains.length > 0 && (
                    <p>
                      Domaines fabricants :{" "}
                      {result.component.manufacturer_domains.join(", ")}
                    </p>
                  )}
                </>
              )}

              <h2>Vérifications</h2>
              {result.verifications.map((v) => (
                <p key={v.id}>
                  <span className={outcomeClass(v.outcome)}>{v.outcome}</span>{" "}
                  <strong>{v.subject}</strong> — {v.detail}
                </p>
              ))}

              <p>
                <span className={result.all_verifications_pass ? "badge ok" : "badge warn"}>
                  {result.all_verifications_pass ? "TOUT VALIDÉ" : "REVIEW REQUISE"}
                </span>{" "}
                {result.version
                  ? `Version V${result.version.number}`
                  : result.versions && result.versions.length > 0
                    ? `Versions : ${result.versions.map((v) => `V${v.number}`).join(", ")}`
                    : ""}
              </p>

              <button onClick={loadReport}>Voir le rapport technique</button>
              {report && <pre className="report">{report}</pre>}
            </>
          )}

          <h2>Tracteur 3D + circuit électrique 12 V</h2>
          {!projectId && <p className="dim">Crée/exécute un projet, puis lance la conception.</p>}
          {projectId && !tractor && (
            <button className="primary" disabled={busy} onClick={buildTractor}>
              {busy ? "Conception 3D..." : "Concevoir le tracteur 3D (pièces + circuit)"}
            </button>
          )}
          {tractor && (
            <>
              <STLViewer files={Object.values(tractor.cad.files)} />
              <p>
                Masse totale estimée : <strong>{tractor.cad.total_mass_kg} kg</strong> ·{" "}
                {tractor.cad.parts.length} pièces · {tractor.cad.total_triangles.toLocaleString()} triangles{" "}
                <span className="badge ok">V{tractor.version?.number ?? "?"}</span>
              </p>

              <h3>Pièces (extrait)</h3>
              <table>
                <tbody>
                  {tractor.cad.parts.slice(0, 14).map((p) => (
                    <tr key={p.name + p.group}>
                      <td>{p.name}</td>
                      <td className="dim">{p.group}</td>
                      <td>{p.mass_kg} kg</td>
                      <td className="dim">{p.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {tractor.cad.parts.length > 14 && (
                <p className="dim">+ {tractor.cad.parts.length - 14} autres pièces (voir tractor_build.json)</p>
              )}

              <h3>Circuit électrique 12 V — {tractor.electrical_design.circuits.length} circuits</h3>
              <table>
                <tbody>
                  {tractor.electrical_design.circuits.map((c) => (
                    <tr key={c.name}>
                      <td>
                        <span className={c.fuse_a ? "badge ok" : "badge warn"}>
                          {c.fuse_a ? `F${c.fuse_a} A` : "sans fusible"}
                        </span>
                      </td>
                      <td>{c.description}</td>
                      <td>{c.current_a} A</td>
                      <td>{c.gauge_mm2} mm²</td>
                      <td>ΔU {c.drop_pct}%</td>
                      <td className="dim">{c.length_m} m</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <img
                src={Api.artifactUrl(`${tractor.project_id}/cad/tractor/electrical_schematic.svg`)}
                alt="Schéma électrique"
                style={{ maxWidth: "100%", border: "1px solid #333", borderRadius: 8 }}
              />

              {tractor.drawings && tractor.drawings.length > 0 && (
                <>
                  <h3>Dessins techniques ({tractor.drawings.length} feuilles DXF + SVG)</h3>
                  <p className="dim">
                    Format DXF (AutoCAD/QCAD/LibreCAD) — vue d'ensemble, pièce par pièce, cablage.
                  </p>
                  <table>
                    <tbody>
                      {tractor.drawings.slice(0, 10).map((s) => (
                        <tr key={s.sheet}>
                          <td>
                            <a href={Api.artifactUrl(s.dxf)} download>{s.sheet}.dxf</a>
                          </td>
                          <td>{s.title}</td>
                          <td className="dim">{s.edges} arêtes · {s.dims} cotes</td>
                          <td>
                            <a href={Api.artifactUrl(s.svg)} target="_blank" rel="noreferrer">aperçu</a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {tractor.drawings.length > 10 && (
                    <p className="dim">+ {tractor.drawings.length - 10} autres feuilles (ensemble + chaque pièce + cablage)</p>
                  )}
                  <img
                    src={Api.artifactUrl(tractor.drawings.find((s) => s.sheet === "ENSEMBLE-00")!.svg)}
                    alt="Mise en plan d'ensemble"
                    style={{ maxWidth: "100%", border: "1px solid #333", borderRadius: 8 }}
                  />
                </>
              )}

              {tractor.deliverables && (
                <>
                  <h3>Livrables AutoCAD (dossier complet)</h3>
                  <p className="dim">{tractor.deliverables.note}</p>
                  <table>
                    <tbody>
                      <tr>
                        <td>
                          <a href={Api.artifactUrl(tractor.deliverables.assembly_3d_dxf)} download>
                            TRACTEUR_3D_ENSEMBLE.dxf
                          </a>
                        </td>
                        <td className="dim">machine complète en 3D (AutoCAD, unités mm)</td>
                      </tr>
                      <tr>
                        <td>
                          <a href={Api.artifactUrl(tractor.deliverables.wiring_csv)} download>
                            CABLAGE_COMPLET.csv
                          </a>
                        </td>
                        <td className="dim">tableau des fils (de → vers, section, fusible)</td>
                      </tr>
                      {tractor.deliverables.bom_csv && (
                        <tr>
                          <td>
                            <a href={Api.artifactUrl(tractor.deliverables.bom_csv)} download>
                              NOMENCLATURE.csv
                            </a>
                          </td>
                          <td className="dim">nomenclature (BOM) : pièces, matières, masses</td>
                        </tr>
                      )}
                      <tr>
                        <td>
                          <a href={Api.artifactUrl(tractor.deliverables.zip)} download>
                            LIVRABLES_COMPLETS.zip ({Math.round(tractor.deliverables.zip_bytes / 1024)} Ko)
                          </a>
                        </td>
                        <td className="dim">
                          tout le dossier organisé par dimension : 3D_MODELES + 2D_PLANS +
                          1D_DONNEES ({tractor.deliverables.file_count} fichiers,
                          {tractor.deliverables.parts_count} pièces 3D)
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </>
              )}

              {tractor.wire_schedule && tractor.wire_schedule.length > 0 && (
                <>
                  <h3>Tableau de cablage ({tractor.wire_schedule.length} fils)</h3>
                  <table>
                    <tbody>
                      {tractor.wire_schedule.map((w) => (
                        <tr key={w.id}>
                          <td><code>{w.id}</code></td>
                          <td>{w.de}</td>
                          <td>→ {w.vers}</td>
                          <td>{w.mm2} mm²</td>
                          <td>{w.couleur}</td>
                          <td>{w.fusible}</td>
                          <td className="dim">{w.a} A</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}

              <h3>Vérifications électriques (indépendantes)</h3>
              {tractor.verifications.map((v) => (
                <p key={v.id}>
                  <span className={outcomeClass(v.outcome)}>{v.outcome}</span> <strong>{v.subject}</strong> — {v.detail}
                </p>
              ))}
              <p className="dim">{tractor.electrical_design.notes.join(" · ")}</p>
            </>
          )}

          <h2>Voiture aéro EV — conception complète (aéro + HT 800 V + BT 12 V)</h2>
          {projectId && !car && (
            <button className="primary" disabled={busy} onClick={buildCar}>
              {busy ? "Conception EV..." : "Concevoir la voiture aéro EV (3D + circuits)"}
            </button>
          )}
          {car && (
            <>
              <STLViewer files={Object.values(car.cad.files)} />
              <p>
                Moteur <strong>{car.scenario.scenario.motor_kw} kW</strong> ·{" "}
                batterie <strong>{car.scenario.scenario.battery_kwh} kWh</strong> ·{" "}
                Cd <strong>{car.scenario.scenario.cd}</strong> ·{" "}
                autonomie <strong>{car.scenario.consistency.range_km} km</strong> ·{" "}
                masse <strong>{car.cad.total_mass_kg} kg</strong> ·{" "}
                {car.cad.parts.length} pièces{" "}
                <span className="badge ok">V{car.version?.number ?? "?"}</span>
              </p>

              <h3>Aérodynamique &amp; bilan de puissance (calculs déterministes)</h3>
              <table>
                <tbody>
                  <tr><td>Traînée à vmax</td><td>{car.scenario.aero.drag_vmax_N} N</td></tr>
                  <tr><td>Puissance aéro à vmax</td><td>{Math.round(car.scenario.aero.power_vmax_W / 1000)} kW</td></tr>
                  <tr><td>Puissance totale à 120 km/h (aéro + roulement)</td><td>{Math.round(car.scenario.aero.total_cruise_W / 1000)} kW</td></tr>
                  <tr><td>Puissance moyenne 0–100 km/h</td><td>{Math.round(car.scenario.acceleration.mean_wheel_power_W / 1000)} kW</td></tr>
                  <tr><td>Moteur requis (règle pic ×2)</td><td>{car.scenario.consistency.required_motor_kw} kW — marge {car.scenario.consistency.motor_margin_kw} kW</td></tr>
                  <tr><td>Masse pack batterie</td><td>{car.scenario.consistency.pack_mass_kg} kg</td></tr>
                </tbody>
              </table>

              <h3>Réseau haute tension {car.hv.system_voltage} V — {car.hv.circuits.length} liaisons</h3>
              <table>
                <tbody>
                  {car.hv.circuits.map((c) => (
                    <tr key={c.name}>
                      <td>{c.description}</td>
                      <td>{c.current_a} A</td>
                      <td>{c.gauge_mm2} mm² ×{c.parallel_per_pole}/pôle</td>
                      <td>ΔU {c.drop_pct}%</td>
                      <td><span className="badge ok">F{c.fuse_a} A</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h3>Réseau basse tension 12 V — {car.lv.circuits.length} circuits</h3>
              <table>
                <tbody>
                  {car.lv.circuits.map((c) => (
                    <tr key={c.name}>
                      <td>{c.description}</td>
                      <td>{c.current_a} A</td>
                      <td>{c.gauge_mm2} mm²</td>
                      <td>ΔU {c.drop_pct}%</td>
                      <td>
                        <span className={c.fuse_a ? "badge ok" : "badge warn"}>
                          {c.fuse_a ? `F${c.fuse_a} A` : "sans fusible"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h3>Vérifications indépendantes ({car.verifications.length})</h3>
              {car.verifications.map((v) => (
                <p key={v.id}>
                  <span className={outcomeClass(v.outcome)}>{v.outcome}</span> <strong>{v.subject}</strong> — {v.detail}
                </p>
              ))}

              {car.drawings && car.drawings.length > 0 && (
                <>
                  <h3>Feuilles 2D ({car.drawings.length} DXF + SVG)</h3>
                  <table>
                    <tbody>
                      {car.drawings.slice(0, 8).map((s) => (
                        <tr key={s.sheet}>
                          <td><a href={Api.artifactUrl(s.dxf)} download>{s.sheet}.dxf</a></td>
                          <td>{s.title}</td>
                          <td><a href={Api.artifactUrl(s.svg)} target="_blank" rel="noreferrer">aperçu</a></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {car.drawings.length > 8 && (
                    <p className="dim">+ {car.drawings.length - 8} autres feuilles</p>
                  )}
                </>
              )}

              <h3>Livrables AutoCAD</h3>
              <table>
                <tbody>
                  <tr>
                    <td><a href={Api.artifactUrl(car.deliverables.assembly_3d_dxf)} download>VOITURE_3D_ENSEMBLE.dxf</a></td>
                    <td className="dim">la voiture complète en 3D (AutoCAD, unités mm)</td>
                  </tr>
                  <tr>
                    <td><a href={Api.artifactUrl(car.deliverables.zip)} download>LIVRABLES_COMPLETS.zip ({Math.round(car.deliverables.zip_bytes / 1024)} Ko)</a></td>
                    <td className="dim">3D_MODELES + 2D_PLANS + 1D_DONNEES ({car.deliverables.file_count} fichiers)</td>
                  </tr>
                </tbody>
              </table>

              <p className="dim">{car.cad_notes[car.cad_notes.length - 1]}</p>
            </>
          )}

          {projectId && (
            <>
              <h3>Assistant IA (NVIDIA, réponse basée sur les données du projet)</h3>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && askAI()}
                  placeholder="Posez une question sur ce projet..."
                  style={{ flex: 1 }}
                />
                <button disabled={asking || !question.trim()} onClick={askAI}>
                  {asking ? "L'IA réfléchit..." : "Demander"}
                </button>
              </div>
              {answer && (
                <pre className="report" style={{ whiteSpace: "pre-wrap" }}>{answer}</pre>
              )}
            </>
          )}
        </section>

        <aside>
          <h2>Historique des projets ({projects.length})</h2>
          <div className="history">
            {projects
              .slice()
              .reverse()
              .map((p) => (
                <button
                  key={p.id}
                  className={p.id === projectId ? "history-item active" : "history-item"}
                  onClick={() => reopenProject(p.id)}
                  disabled={busy}
                  title={p.description}
                >
                  <span className="history-name">{p.name}</span>
                  <small>
                    {new Date(p.created_at).toLocaleString()} · {p.id}
                  </small>
                </button>
              ))}
            {projects.length === 0 && <p className="dim">Aucun projet enregistré.</p>}
          </div>

          <h2>Événements temps réel ({events.length})</h2>
          <div className="feed">
            {events
              .slice()
              .reverse()
              .map((e, i) => (
                <div key={i} className="event">
                  <span style={{ color: EVENT_COLORS[e.kind] ?? "var(--accent)" }}>{e.kind}</span>
                  <small>{new Date(e.timestamp).toLocaleTimeString()}</small>
                  <pre>{JSON.stringify(e.payload, null, 0).slice(0, 140)}</pre>
                </div>
              ))}
            {events.length === 0 && <p className="dim">En attente d'événements...</p>}
          </div>
        </aside>
      </main>
    </div>
  );
}
