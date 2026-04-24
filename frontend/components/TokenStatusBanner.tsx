"use client";

/**
 * TokenStatusBanner
 *
 * Polls /auth/upstox/status every 60 s.  When the Upstox token is expired
 * (or missing) it shows a sticky warning banner with a "Login Now" button.
 *
 * Clicking "Login Now" opens a modal that walks the user through the
 * 3-step daily login:
 *   1. Click "Start Login" → backend launches headless browser, fills mobile,
 *      clicks "Get OTP" on Upstox.  SMS is sent to the user's phone.
 *   2. User types the 6-digit SMS OTP into the modal input.
 *   3. Click "Submit OTP" → backend fills PIN + TOTP automatically.
 *      Token is saved and live trading resumes.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Phase =
  | "idle"              // modal closed / not started
  | "starting"          // waiting for /start-login response
  | "otp_input"         // backend paused — user must enter OTP
  | "submitting"        // waiting for /submit-otp response
  | "success"           // login complete
  | "error";            // something went wrong

interface ModalState {
  phase: Phase;
  sessionId: string;
  otp: string;
  message: string;
  expiresAt: string;
}

const POLL_INTERVAL_MS = 60_000; // check token status every 60 s

export function TokenStatusBanner() {
  const [tokenExpired, setTokenExpired] = useState(false);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [liveStatus, setLiveStatus] = useState<{ok: boolean; nifty_ltp: number | null; error: string | null} | null>(null);

  const [state, setState] = useState<ModalState>({
    phase: "idle",
    sessionId: "",
    otp: "",
    message: "",
    expiresAt: "",
  });

  const otpInputRef = useRef<HTMLInputElement>(null);

  // ── Poll token status ────────────────────────────────────────────────────
  const checkStatus = useCallback(async () => {
    try {
      const s = await api.upstoxStatus();
      setTokenExpired(!s.ready);
      setExpiresAt(s.token_expires_at);
      // If token is ready, also verify live API connectivity
      if (s.ready) {
        try {
          const t = await api.upstoxTest();
          setLiveStatus(t);
        } catch {
          setLiveStatus({ ok: false, nifty_ltp: null, error: "Could not reach backend" });
        }
      }
    } catch {
      // Backend might not be running — silently ignore
    }
  }, []);

  useEffect(() => {
    checkStatus();
    const id = setInterval(checkStatus, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [checkStatus]);

  // Focus OTP input when we reach that phase
  useEffect(() => {
    if (state.phase === "otp_input") {
      setTimeout(() => otpInputRef.current?.focus(), 100);
    }
  }, [state.phase]);

  // ── Handlers ─────────────────────────────────────────────────────────────
  const openModal = () => {
    setState({ phase: "idle", sessionId: "", otp: "", message: "", expiresAt: "" });
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setState((s) => ({ ...s, phase: "idle", otp: "" }));
  };

  const startLogin = async () => {
    setState((s) => ({ ...s, phase: "starting", message: "" }));
    try {
      const res = await api.upstoxStartLogin();
      if (res.status === "otp_required" && res.session_id) {
        setState((s) => ({
          ...s,
          phase: "otp_input",
          sessionId: res.session_id!,
          message:
            "An OTP has been sent to your registered mobile number. " +
            "Enter it below to complete login.",
        }));
      } else if (res.status === "success") {
        setState((s) => ({
          ...s,
          phase: "success",
          expiresAt: res.token_expires_at || "",
        }));
        setTokenExpired(false);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setState((s) => ({
        ...s,
        phase: "error",
        message: `Failed to start login: ${msg}`,
      }));
    }
  };

  const submitOtp = async () => {
    if (!state.otp.trim()) return;
    setState((s) => ({ ...s, phase: "submitting", message: "" }));
    try {
      const res = await api.upstoxSubmitOtp(state.sessionId, state.otp.trim());
      setState((s) => ({
        ...s,
        phase: "success",
        expiresAt: res.token_expires_at || "",
      }));
      setTokenExpired(false);
      setExpiresAt(res.token_expires_at || null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setState((s) => ({
        ...s,
        phase: "error",
        message: `OTP failed: ${msg}`,
      }));
    }
  };

  const handleOtpKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") submitOtp();
  };

  // ── Render ───────────────────────────────────────────────────────────────
  // When token is valid, show a slim green status bar with live Nifty price
  if (!tokenExpired) {
    if (!liveStatus) return null;
    return (
      <div className={`w-full border-b px-4 py-1.5 flex items-center gap-3 text-xs ${
        liveStatus.ok
          ? "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/30 dark:border-emerald-900 dark:text-emerald-300"
          : "bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-950/30 dark:border-rose-900 dark:text-rose-300"
      }`}>
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${liveStatus.ok ? "bg-emerald-500 animate-pulse" : "bg-rose-500"}`} />
        {liveStatus.ok ? (
          <>
            <span className="font-semibold">Upstox live data connected</span>
            {liveStatus.nifty_ltp && (
              <span className="text-emerald-600 dark:text-emerald-400 font-medium">
                NIFTY 50: ₹{liveStatus.nifty_ltp.toFixed(2)}
              </span>
            )}
            {expiresAt && (
              <span className="text-emerald-600/70 dark:text-emerald-500/70 ml-auto">
                Token valid until {expiresAt}
              </span>
            )}
          </>
        ) : (
          <>
            <span className="font-semibold">Upstox API error</span>
            <span className="opacity-80">{liveStatus.error}</span>
            <button onClick={openModal} className="ml-auto underline font-medium">Re-login</button>
          </>
        )}
      </div>
    );
  }

  return (
    <>
      {/* ── Sticky banner ───────────────────────────────────────────────── */}
      <div className="w-full bg-amber-50 border-b border-amber-200 text-amber-900 px-4 py-2 flex items-center justify-between text-sm">
        <span className="font-medium">
          ⚠️ Upstox token expired — live prices unavailable.
          {expiresAt && (
            <span className="font-normal ml-1">
              (expired: {expiresAt})
            </span>
          )}
        </span>
        <button
          onClick={openModal}
          className="ml-4 bg-amber-500 hover:bg-amber-600 text-white text-xs font-semibold px-3 py-1 rounded-md transition-colors"
        >
          Login Now
        </button>
      </div>

      {/* ── Modal ───────────────────────────────────────────────────────── */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={(e) => e.target === e.currentTarget && closeModal()}
        >
          <div className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
              <h2 className="text-lg font-semibold">Upstox Daily Login</h2>
              <button
                onClick={closeModal}
                className="text-slate-400 hover:text-slate-600 text-xl leading-none"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {/* Body */}
            <div className="px-6 py-5 space-y-4">
              {/* ── idle ── */}
              {state.phase === "idle" && (
                <>
                  <p className="text-sm text-slate-600 dark:text-slate-300">
                    Your Upstox access token has expired. Click{" "}
                    <strong>Start Login</strong> to begin the daily login. A
                    6-digit SMS OTP will be sent to your phone — you&apos;ll enter
                    it here. PIN and TOTP are handled automatically.
                  </p>
                  <button
                    onClick={startLogin}
                    className="w-full bg-brand-500 hover:bg-brand-600 text-white font-semibold py-2 rounded-lg transition-colors"
                  >
                    Start Login
                  </button>
                </>
              )}

              {/* ── starting ── */}
              {state.phase === "starting" && (
                <div className="flex flex-col items-center gap-3 py-4">
                  <Spinner />
                  <p className="text-sm text-slate-500">
                    Launching browser and requesting OTP from Upstox…
                  </p>
                  <p className="text-xs text-slate-400 text-center">
                    This usually takes 15–30 seconds. An SMS will be sent to
                    your registered mobile number.
                  </p>
                </div>
              )}

              {/* ── otp_input ── */}
              {state.phase === "otp_input" && (
                <>
                  {state.message && (
                    <p className="text-sm text-slate-600 dark:text-slate-300">
                      {state.message}
                    </p>
                  )}
                  <div>
                    <label className="block text-sm font-medium mb-1">
                      SMS OTP (6 digits)
                    </label>
                    <input
                      ref={otpInputRef}
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={6}
                      placeholder="123456"
                      value={state.otp}
                      onChange={(e) =>
                        setState((s) => ({ ...s, otp: e.target.value.replace(/\D/g, "") }))
                      }
                      onKeyDown={handleOtpKey}
                      className="w-full border border-slate-300 dark:border-slate-600 rounded-lg px-3 py-2 text-center text-2xl tracking-widest focus:outline-none focus:ring-2 focus:ring-brand-500 dark:bg-slate-700"
                    />
                  </div>
                  <button
                    onClick={submitOtp}
                    disabled={state.otp.length < 4}
                    className="w-full bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white font-semibold py-2 rounded-lg transition-colors"
                  >
                    Submit OTP
                  </button>
                </>
              )}

              {/* ── submitting ── */}
              {state.phase === "submitting" && (
                <div className="flex flex-col items-center gap-3 py-4">
                  <Spinner />
                  <p className="text-sm text-slate-500">
                    Verifying OTP and completing login…
                  </p>
                  <p className="text-xs text-slate-400 text-center">
                    PIN and TOTP are being filled in automatically.
                  </p>
                </div>
              )}

              {/* ── success ── */}
              {state.phase === "success" && (
                <div className="flex flex-col items-center gap-3 py-4 text-center">
                  <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center text-2xl">
                    ✓
                  </div>
                  <p className="text-green-700 font-semibold">Login successful!</p>
                  {state.expiresAt && (
                    <p className="text-xs text-slate-500">
                      Token valid until: {state.expiresAt}
                    </p>
                  )}
                  <p className="text-sm text-slate-500">
                    Live prices and auto-trading are now active.
                  </p>
                  <button
                    onClick={closeModal}
                    className="mt-2 bg-green-600 hover:bg-green-700 text-white font-semibold px-6 py-2 rounded-lg transition-colors"
                  >
                    Done
                  </button>
                </div>
              )}

              {/* ── error ── */}
              {state.phase === "error" && (
                <>
                  <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3">
                    <p className="text-sm text-red-700 dark:text-red-300">
                      {state.message}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() =>
                        setState((s) => ({ ...s, phase: "idle", message: "" }))
                      }
                      className="flex-1 border border-slate-300 hover:bg-slate-50 text-slate-700 font-medium py-2 rounded-lg transition-colors"
                    >
                      Try Again
                    </button>
                    <button
                      onClick={closeModal}
                      className="flex-1 bg-slate-600 hover:bg-slate-700 text-white font-medium py-2 rounded-lg transition-colors"
                    >
                      Close
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Spinner() {
  return (
    <div className="w-8 h-8 border-2 border-slate-200 border-t-brand-500 rounded-full animate-spin" />
  );
}
