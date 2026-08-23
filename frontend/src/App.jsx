import { useEffect, useState } from "react";

const API = "http://localhost:8000";

function App() {
  const [mode, setMode] = useState(null);
  const [name, setName] = useState("");
  const [roomInput, setRoomInput] = useState("");
  const [text, setText] = useState("");

  const [roomCode, setRoomCode] = useState("");
  const [role, setRole] = useState("");

  const [profile, setProfile] = useState(null);
  const [roomStatus, setRoomStatus] = useState("");

  const [result, setResult] = useState(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // -----------------------------
  // CREATE ROOM
  // -----------------------------

  async function createRoom() {
    if (!name.trim()) {
      setError("Please enter your name.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API}/api/rooms`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          party_a_name: name.trim(),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail)
        );
      }

      setRoomCode(data.room_code);
      setRole("a");
      setMode("intake");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not create room."
      );
    } finally {
      setLoading(false);
    }
  }

  // -----------------------------
  // JOIN ROOM
  // -----------------------------

  async function joinRoom() {
    if (!name.trim()) {
      setError("Please enter your name.");
      return;
    }

    if (!roomInput.trim()) {
      setError("Please enter the room code.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const code = roomInput.trim().toUpperCase();

      const response = await fetch(
        `${API}/api/rooms/${code}/join`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            party_b_name: name.trim(),
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail)
        );
      }

      setRoomCode(data.room_code);
      setRole("b");
      setMode("intake");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not join room."
      );
    } finally {
      setLoading(false);
    }
  }

  // -----------------------------
  // EXTRACT + SUBMIT PROFILE
  // -----------------------------

  async function submitPrivateBrief() {
    if (!text.trim()) return;

    setLoading(true);
    setError("");

    try {
      const extractResponse = await fetch(
        `${API}/api/rooms/${roomCode}/extract`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            role,
            party_name: name.trim(),
            free_text: text,
          }),
        }
      );

      const extracted = await extractResponse.json();

      if (!extractResponse.ok) {
        throw new Error(
          typeof extracted.detail === "string"
            ? extracted.detail
            : JSON.stringify(extracted.detail)
        );
      }

      const constraintsResponse = await fetch(
        `${API}/api/rooms/${roomCode}/constraints`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            role,
            profile: extracted,
          }),
        }
      );

      const constraintResult = await constraintsResponse.json();

      if (!constraintsResponse.ok) {
        throw new Error(
          typeof constraintResult.detail === "string"
            ? constraintResult.detail
            : JSON.stringify(constraintResult.detail)
        );
      }

      setProfile(extracted);
      setRoomStatus("collecting_constraints");
    } catch (err) {
      console.error("Mediator error:", err);

      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong."
      );
    } finally {
      setLoading(false);
    }
  }
  // -----------------------------
  // DERIVED ROOM STATUS
  // -----------------------------

  const negotiating = roomStatus === "negotiating";
  const done = roomStatus === "done";
  const statusError = roomStatus === "error";

  // -----------------------------
  // GET FINAL RESULT
  // -----------------------------

  async function fetchResult() {
    try {
      const response = await fetch(
        `${API}/api/rooms/${roomCode}/result?role=${role}`
      );

      if (!response.ok) {
        const message = await response.text();
        console.error(
          "Result request failed:",
          response.status,
          message
        );
        return false;
      }

      const data = await response.json();

      console.log("FINAL RESULT RECEIVED:", data);

      setResult(data);
      setRoomStatus("done");
      return true;
    } catch (err) {
      console.error("Result error:", err);
      return false;
    }
  }
  // -----------------------------
  // ROOM STATUS POLLING
  // -----------------------------

  useEffect(() => {
    if (!roomCode || !profile) return;

    let cancelled = false;
    let interval;

    async function checkStatus() {
      try {
        const response = await fetch(
          `${API}/api/rooms/${roomCode}/status`
        );

        if (!response.ok) {
          console.error(
            "Status request failed:",
            response.status
          );
          return;
        }

        const data = await response.json();

        if (cancelled) return;

        console.log("ROOM STATUS:", data.status);
        console.log("ROOM ERROR:", data.error_message);

        setRoomStatus(data.status);

        // Negotiation has finished.
        if (data.status === "done") {
          console.log("NEGOTIATION DONE — STOPPING POLLING");

          clearInterval(interval);

          const resultResponse = await fetch(
            `${API}/api/rooms/${roomCode}/result?role=${role}`
          );

          if (!resultResponse.ok) {
            const message = await resultResponse.text();

            console.error(
              "FINAL RESULT FAILED:",
              resultResponse.status,
              message
            );

            return;
          }

          const finalData = await resultResponse.json();

          console.log(
            "FINAL RESULT:",
            finalData
          );

          if (!cancelled) {
            setResult(finalData);
            setRoomStatus("done");
          }

          return;
        }

        // Negotiation failed.
        if (data.status === "error") {
          console.log("NEGOTIATION ERROR — STOPPING POLLING");

          clearInterval(interval);

          setError(
            data.error_message ||
            "The negotiation could not be completed."
          );

          return;
        }

      } catch (err) {
        console.error(
          "Status polling error:",
          err
        );
      }
    }

    // Check immediately.
    checkStatus();

    // Continue checking every 2 seconds.
    interval = setInterval(
      checkStatus,
      2000
    );

    return () => {
      cancelled = true;
      clearInterval(interval);
    };

  }, [roomCode, profile]);
  // -----------------------------
  // RESET
  // -----------------------------

  function resetApp() {
    setMode(null);
    setName("");
    setRoomInput("");
    setText("");
    setRoomCode("");
    setRole("");
    setProfile(null);
    setRoomStatus("");
    setResult(null);
    setLoading(false);
    setError("");
  }

  // ==================================================
  // FINAL RESULT SCREEN
  // ==================================================

  if (result) {
    const verdict = result.verdict;
    const hasAgreement = result.final_terms?.length > 0;
    console.log("FINAL TERMS:", result.final_terms);
    console.log("HAS AGREEMENT:", hasAgreement);
    return (
      <div className="min-h-screen bg-[#08090c] px-6 py-12 text-white">
        <div className="mx-auto max-w-4xl">

          {/* HEADER */}

          <div className="mb-14 flex items-center justify-between">

            <div className="text-xl font-semibold tracking-tight">
              mediator
              <span className="text-violet-400">.</span>
            </div>

            <div
              className={
                hasAgreement
                  ? "rounded-full border border-emerald-400/20 bg-emerald-400/5 px-4 py-2 text-sm text-emerald-300"
                  : "rounded-full border border-red-400/20 bg-red-400/5 px-4 py-2 text-sm text-red-300"
              }
            >
              {hasAgreement
                ? "Agreement reached"
                : "No agreement reached"}
            </div>

          </div>

          {/* HERO */}

          <div className="mb-12">

            {hasAgreement ? (
              <>
                <p className="mb-3 text-sm font-medium uppercase tracking-[0.2em] text-violet-400">
                  Negotiation complete
                </p>

                <h1 className="text-5xl font-semibold tracking-tight md:text-7xl">
                  You found
                  <br />
                  <span className="text-white/40">
                    the middle.
                  </span>
                </h1>

                <p className="mt-6 max-w-2xl text-lg leading-8 text-white/45">
                  Your agents negotiated privately and reached
                  an agreement without exposing either person's
                  original position.
                </p>
              </>
            ) : (
              <>
                <p className="mb-3 text-sm font-medium uppercase tracking-[0.2em] text-red-400">
                  Negotiation complete
                </p>

                <h1 className="text-5xl font-semibold tracking-tight md:text-7xl">
                  No workable
                  <br />
                  <span className="text-white/40">
                    agreement.
                  </span>
                </h1>

                <p className="mt-6 max-w-2xl text-lg leading-8 text-white/45">
                  Your agents could not find terms that satisfy
                  both parties' non-negotiable requirements.
                </p>
              </>
            )}

          </div>
         {/* FINAL AGREEMENT */}

          {result.final_terms?.length > 0 && (
            <section className="rounded-3xl border border-white/10 bg-white/[0.03] p-6 md:p-8">

              <div className="mb-7">
                <p className="text-xs uppercase tracking-[0.2em] text-white/30">
                  Final agreement
                </p>

                <h2 className="mt-2 text-2xl font-semibold">
                  What you both agreed to
                </h2>
              </div>

              <div className="grid gap-4 md:grid-cols-2">

                {result.final_terms.map((term) => (
                  <div
                    key={term.key}
                    className="rounded-2xl border border-white/10 bg-black/20 p-5"
                  >
                    <p className="text-xs uppercase tracking-wider text-white/30">
                      {term.description}
                    </p>

                    <p className="mt-3 text-lg font-medium">
                      {formatValue(term.value)}
                    </p>
                  </div>
                ))}

              </div>

            </section>
          )}
          {/* FAIRNESS */}

          {result.verdict && (
            <section className="mt-6 rounded-3xl border border-white/10 bg-white/[0.03] p-6 md:p-8">

              <div className="flex flex-col gap-8 md:flex-row md:items-center">

                <div className="flex-1">
                  <p className="text-xs uppercase tracking-[0.2em] text-white/30">
                    Fairness check
                  </p>

                  <h2 className="mt-2 text-2xl font-semibold">
                    {result.verdict.is_balanced
                      ? "Balanced agreement"
                      : "Compromise Check"}
                  </h2>

                  <p className="mt-3 text-sm leading-6 text-white/45">
                    An independent fairness layer reviewed
                    what both sides gained and gave up.
                  </p>
                </div>

                <div className="flex h-32 w-32 shrink-0 items-center justify-center rounded-full border border-violet-400/20 bg-violet-400/5">
                  <div className="text-center">
                    <div className="text-4xl font-bold">
                      {result.verdict.balance_score}
                    </div>

                    <div className="text-xs text-white/30">
                      / 100
                    </div>
                  </div>
                </div>

              </div>
            </section>
          )}

      {/* YOUR PERSONALIZED OUTCOME */}

      {result.verdict && (
        <section className="mt-6 rounded-3xl border border-white/10 bg-white/[0.03] p-6 md:p-8">

          <p className="text-xs uppercase tracking-[0.2em] text-violet-400">
            Your outcome
          </p>

          <h3 className="mt-2 text-xl font-semibold">
            What you gave up
          </h3>

          <p className="mt-4 text-sm leading-7 text-white/50">
            {result.verdict.your_summary}
          </p>

        </section>
      )}
          {/* NEGOTIATION ROUNDS */}

          {result.all_proposals?.length > 0 && (
            <section className="mt-6 rounded-3xl border border-white/10 bg-white/[0.03] p-6 md:p-8">

              <p className="text-xs uppercase tracking-[0.2em] text-white/30">
                Negotiation history
              </p>

              <h2 className="mt-2 text-2xl font-semibold">
                How the agents reached agreement
              </h2>

              <div className="mt-8 space-y-4">

                {result.all_proposals.map((proposal) => (
                  <div
                    key={proposal.round_number}
                    className="rounded-2xl border border-white/10 bg-black/20 p-5"
                  >

                    <div className="flex items-center justify-between">

                      <div className="flex items-center gap-3">

                        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/5 text-xs">
                          {proposal.round_number}
                        </span>

                        <span className="text-sm font-medium">
                          {proposal.speaker === "agent_a"
                            ? "Agent A"
                            : "Agent B"}
                        </span>

                      </div>

                      <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase text-white/40">
                        {proposal.action}
                      </span>

                    </div>

                    <p className="mt-4 text-sm leading-6 text-white/45">
                      {proposal.rationale}
                    </p>

                    {proposal.conceded_on?.length > 0 && (
                      <p className="mt-3 text-xs text-violet-300/70">
                        Conceded:
                        {" "}
                        {proposal.conceded_on.join(", ")}
                      </p>
                    )}

                  </div>
                ))}

              </div>
            </section>
          )}

          {/* PRIVACY */}

          <section className="mt-6 rounded-3xl border border-violet-400/20 bg-violet-400/5 p-6 md:p-8">

            <div className="flex gap-4">

              <div className="text-2xl">
                🔐
              </div>

              <div>
                <h2 className="font-semibold">
                  Your private positions stayed private.
                </h2>

                <p className="mt-2 text-sm leading-6 text-white/45">
                  Neither party's raw intake was shared with
                  the other. Each agent negotiated using its
                  own private constraint profile.
                </p>
              </div>

            </div>
          </section>

          {/* FOOTER */}

          <div className="mt-10 flex items-center justify-between">

            <span className="text-xs text-white/25">
              Room {roomCode}
            </span>

            <button
              onClick={resetApp}
              className="rounded-2xl border border-white/10 px-5 py-3 text-sm text-white/50 transition hover:border-white/20 hover:text-white"
            >
              Start a new negotiation
            </button>

          </div>

        </div>
      </div>
    );
  }

  // ==================================================
  // PRIVATE PROFILE / WAITING
  // ==================================================

  if (profile) {
    const negotiating = roomStatus === "negotiating";
    const done = roomStatus === "done";

    return (
      <div className="min-h-screen bg-[#08090c] px-6 py-12 text-white">
        <div className="mx-auto max-w-3xl">

          <div className="mb-12 flex items-center justify-between">

            <div className="text-xl font-semibold">
              mediator
              <span className="text-violet-400">.</span>
            </div>

            <div className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/60">
              Room {roomCode}
            </div>

          </div>

          <div className="mb-10">

            <p className="mb-3 text-sm font-medium uppercase tracking-[0.2em] text-violet-400">
              Private brief created
            </p>

            <h1 className="text-4xl font-semibold md:text-5xl">
              Your agent knows what matters.
            </h1>

            <p className="mt-4 text-lg leading-8 text-white/50">
              Your private constraints stay hidden from the
              other party.
            </p>

          </div>

          <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-6 md:p-8">

            <p className="mb-6 text-sm leading-6 text-white/40">
              {profile.scenario_summary}
            </p>

            <div className="space-y-3">

              {profile.constraints?.map((constraint) => (
                <div
                  key={constraint.key}
                  className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 p-4"
                >

                  <div>

                    <p className="font-medium">
                      {constraint.description}
                    </p>

                    <p className="mt-1 text-xs uppercase tracking-wider text-white/30">
                      {constraint.type}
                    </p>

                  </div>

                  <span className="text-sm text-white/50">
                    Priority {constraint.priority}
                  </span>

                </div>
              ))}

            </div>

            <div className="mt-8 rounded-2xl border border-violet-400/20 bg-violet-400/5 p-5">
              <p className="text-sm leading-6 text-white/60">
                🔒 Your private brief is only used by your
                negotiating agent.
              </p>
            </div>

          </div>

          {/* ROOM CODE */}

          <div className="mt-6 rounded-3xl border border-white/10 bg-white/[0.03] p-8 text-center">

            <p className="text-xs uppercase tracking-[0.2em] text-white/30">
              Room code
            </p>

            <div className="mt-3 text-5xl font-bold tracking-[0.2em]">
              {roomCode}
            </div>

            <p className="mt-4 text-sm text-white/40">
              {role === "a"
                ? "Share this code with the other person."
                : "You joined the negotiation."}
            </p>

          </div>

         {/* STATUS */}

          <div className="mt-6 rounded-3xl border border-white/10 bg-white/[0.03] p-6">

            {roomStatus !== "negotiating" &&
              roomStatus !== "done" &&
              roomStatus !== "error" && (
              <>
                <div className="flex items-center gap-3">
                  <span className="h-3 w-3 animate-pulse rounded-full bg-violet-400" />

                  <p className="font-medium">
                    Waiting for the other person...
                  </p>
                </div>

                <p className="mt-3 text-sm text-white/40">
                  Once both private briefs are submitted,
                  your agents will negotiate automatically.
                </p>
              </>
            )}

            {roomStatus === "negotiating" && (
              <>
                <div className="flex items-center gap-3">
                  <span className="h-3 w-3 animate-pulse rounded-full bg-emerald-400" />

                  <p className="font-medium">
                    Your agents are negotiating...
                  </p>
                </div>

                <p className="mt-3 text-sm text-white/40">
                  Your private constraints remain hidden.
                </p>
              </>
            )}

            {roomStatus === "done" && (
              <>
                <div className="flex items-center gap-3">
                  <span className="h-3 w-3 rounded-full bg-emerald-400" />

                  <p className="font-medium">
                    Negotiation complete.
                  </p>
                </div>

                <p className="mt-3 text-sm text-white/40">
                  Loading the agreement...
                </p>
              </>
            )}

          </div>

          <button
            onClick={resetApp}
            className="mt-6 text-sm text-white/40 hover:text-white"
          >
            ← Start over
          </button>

        </div>
      </div>
    );
  }

  // ==================================================
  // INTAKE
  // ==================================================

  if (mode === "intake") {
    return (
      <div className="min-h-screen bg-[#08090c] px-6 py-12 text-white">
        <div className="mx-auto max-w-3xl">

          <div className="mb-12 flex items-center justify-between">

            <div className="text-xl font-semibold">
              mediator
              <span className="text-violet-400">.</span>
            </div>

            <div className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/50">
              Room {roomCode}
            </div>

          </div>

          <p className="mb-3 text-sm uppercase tracking-[0.2em] text-violet-400">
            Private intake
          </p>

          <h1 className="text-4xl font-semibold md:text-6xl">
            What really matters to you?
          </h1>

          <p className="mt-5 text-lg leading-8 text-white/45">
            Tell your agent your real constraints,
            preferences, and priorities.
          </p>

          <div className="mt-10 overflow-hidden rounded-3xl border border-white/10 bg-white/[0.03]">

            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Tell me what you're trying to negotiate..."
              rows={8}
              className="w-full resize-none bg-transparent p-6 text-base leading-7 text-white outline-none placeholder:text-white/20"
            />

            <div className="flex items-center justify-between border-t border-white/10 p-4">

              <span className="px-2 text-xs text-white/30">
                🔒 Only your agent sees this.
              </span>

              <button
                onClick={submitPrivateBrief}
                disabled={!text.trim() || loading}
                className="rounded-2xl bg-white px-6 py-3 text-sm font-semibold text-black transition hover:bg-white/90 disabled:opacity-30"
              >
                {loading
                  ? "Understanding..."
                  : "Give this to my agent →"}
              </button>

            </div>

          </div>

          {error && (
            <div className="mt-4 whitespace-pre-wrap rounded-2xl border border-red-400/20 bg-red-400/5 p-4 text-sm text-red-300">
              {error}
            </div>
          )}

        </div>
      </div>
    );
  }

  // ==================================================
  // CREATE
  // ==================================================

  if (mode === "create") {
    return (
      <SimpleNameScreen
        title="Start a private negotiation."
        description="Create a room and invite the other person with a simple code."
        name={name}
        setName={setName}
        loading={loading}
        error={error}
        onBack={resetApp}
        onSubmit={createRoom}
        buttonText="Create room →"
      />
    );
  }

  // ==================================================
  // JOIN
  // ==================================================

  if (mode === "join") {
    return (
      <div className="min-h-screen bg-[#08090c] px-6 py-12 text-white">
        <div className="mx-auto max-w-xl">

          <button
            onClick={resetApp}
            className="mb-16 text-sm text-white/40 hover:text-white"
          >
            ← Back
          </button>

          <p className="mb-3 text-sm uppercase tracking-[0.2em] text-violet-400">
            Join negotiation
          </p>

          <h1 className="text-4xl font-semibold md:text-5xl">
            Enter your room.
          </h1>

          <p className="mt-4 text-lg leading-8 text-white/45">
            Enter the code shared by the other person.
          </p>

          <div className="mt-10 space-y-4">

            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name"
              className="w-full rounded-2xl border border-white/10 bg-white/[0.03] px-5 py-4 text-white outline-none placeholder:text-white/20"
            />

            <input
              value={roomInput}
              onChange={(e) =>
                setRoomInput(e.target.value.toUpperCase())
              }
              placeholder="Room code"
              maxLength={6}
              className="w-full rounded-2xl border border-white/10 bg-white/[0.03] px-5 py-4 text-center text-2xl font-semibold tracking-[0.25em] text-white outline-none placeholder:text-white/20"
            />

            <button
              onClick={joinRoom}
              disabled={loading}
              className="w-full rounded-2xl bg-white px-6 py-4 font-semibold text-black transition hover:bg-white/90 disabled:opacity-30"
            >
              {loading ? "Joining..." : "Join room →"}
            </button>

          </div>

          {error && (
            <div className="mt-4 whitespace-pre-wrap rounded-2xl border border-red-400/20 bg-red-400/5 p-4 text-sm text-red-300">
              {error}
            </div>
          )}

        </div>
      </div>
    );
  }

  // ==================================================
  // HOME
  // ==================================================

  return (
    <div className="min-h-screen bg-[#08090c] text-white">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-6">

        <nav className="flex items-center justify-between py-7">

          <div className="text-xl font-semibold tracking-tight">
            mediator
            <span className="text-violet-400">.</span>
          </div>

          <div className="flex items-center gap-2 text-xs text-white/40">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            Private by design
          </div>

        </nav>

        <main className="flex flex-1 flex-col justify-center pb-20">

          <div className="mx-auto w-full max-w-3xl">

            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-xs text-white/50">
              <span className="text-violet-400">✦</span>
              AI-powered conflict resolution
            </div>

            <h1 className="text-5xl font-semibold leading-[1.05] tracking-[-0.04em] md:text-7xl">
              Let your agents
              <br />
              <span className="text-white/40">
                find the middle.
              </span>
            </h1>

            <p className="mt-7 max-w-2xl text-lg leading-8 text-white/45">
              Two private AI agents negotiate your real
              constraints without exposing your raw positions.
            </p>

            <div className="mt-12 grid gap-4 md:grid-cols-2">

              <button
                onClick={() => {
                  setMode("create");
                  setError("");
                }}
                className="rounded-3xl border border-white/10 bg-white/[0.03] p-8 text-left transition hover:border-violet-400/30"
              >
                <div className="text-2xl text-violet-400">
                  ✦
                </div>

                <h2 className="mt-5 text-xl font-semibold">
                  Create a room
                </h2>

                <p className="mt-2 text-sm leading-6 text-white/40">
                  Start a negotiation and invite someone
                  with a room code.
                </p>
              </button>

              <button
                onClick={() => {
                  setMode("join");
                  setError("");
                }}
                className="rounded-3xl border border-white/10 bg-white/[0.03] p-8 text-left transition hover:border-violet-400/30"
              >
                <div className="text-2xl">
                  →
                </div>

                <h2 className="mt-5 text-xl font-semibold">
                  Join a room
                </h2>

                <p className="mt-2 text-sm leading-6 text-white/40">
                  Enter a room code and negotiate with
                  another person's agent.
                </p>
              </button>

            </div>

          </div>
        </main>
      </div>
    </div>
  );
}

// ==================================================
// SMALL REUSABLE NAME SCREEN
// ==================================================

function SimpleNameScreen({
  title,
  description,
  name,
  setName,
  loading,
  error,
  onBack,
  onSubmit,
  buttonText,
}) {
  return (
    <div className="min-h-screen bg-[#08090c] px-6 py-12 text-white">
      <div className="mx-auto max-w-xl">

        <button
          onClick={onBack}
          className="mb-16 text-sm text-white/40 hover:text-white"
        >
          ← Back
        </button>

        <p className="mb-3 text-sm uppercase tracking-[0.2em] text-violet-400">
          Create negotiation
        </p>

        <h1 className="text-4xl font-semibold md:text-5xl">
          {title}
        </h1>

        <p className="mt-4 text-lg leading-8 text-white/45">
          {description}
        </p>

        <div className="mt-10">

          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name"
            className="w-full rounded-2xl border border-white/10 bg-white/[0.03] px-5 py-4 text-white outline-none placeholder:text-white/20"
          />

          <button
            onClick={onSubmit}
            disabled={loading}
            className="mt-4 w-full rounded-2xl bg-white px-6 py-4 font-semibold text-black transition hover:bg-white/90 disabled:opacity-30"
          >
            {loading ? "Creating room..." : buttonText}
          </button>

        </div>

        {error && (
          <div className="mt-4 whitespace-pre-wrap rounded-2xl border border-red-400/20 bg-red-400/5 p-4 text-sm text-red-300">
            {error}
          </div>
        )}

      </div>
    </div>
  );
}

// ==================================================
// FORMAT FINAL VALUES
// ==================================================

function formatValue(value) {
  if (value === null || value === undefined) {
    return "Not specified";
  }

  if (typeof value === "string") {
    return value.replaceAll("_", " ");
  }

  if (typeof value === "number") {
    return value.toLocaleString("en-IN");
  }

  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, val]) => {
        const cleanKey = key
          .replaceAll("_", " ")
          .replace(/\b\w/g, (letter) =>
            letter.toUpperCase()
          );

        if (typeof val === "number") {
          return `${cleanKey}: ${val.toLocaleString("en-IN")}`;
        }

        return `${cleanKey}: ${String(val).replaceAll(
          "_",
          " "
        )}`;
      })
      .join(" • ");
  }

  return String(value);
}

export default App;