import React, { useState } from "react";

const MIN_LENGTH = 8;

// Email + password sign in / create account. The server re-checks everything;
// these checks just give instant feedback and block the submit button.
function AuthForm({ onSubmit }) {
  const [mode, setMode] = useState("signin"); // "signin" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const signup = mode === "signup";
  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  const tooShort = signup && password.length > 0 && password.length < MIN_LENGTH;
  const mismatch = signup && confirm.length > 0 && password !== confirm;
  const matches = signup && confirm.length > 0 && password === confirm;

  const canSubmit = signup
    ? emailOk && password.length >= MIN_LENGTH && password === confirm
    : emailOk && password.length > 0;

  const switchMode = () => {
    setMode(signup ? "signin" : "signup");
    setPassword("");
    setConfirm("");
    setError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit || busy) return; // strict: never submit unless confirmation matches
    setBusy(true);
    setError("");
    try {
      await onSubmit({ mode, email: email.trim(), password, confirm });
    } catch (err) {
      setError(err?.response?.data?.error || "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={handleSubmit} noValidate>
      <div className="auth-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={!signup} className={!signup ? "on" : ""} onClick={() => signup && switchMode()}>
          Sign in
        </button>
        <button type="button" role="tab" aria-selected={signup} className={signup ? "on" : ""} onClick={() => !signup && switchMode()}>
          Create account
        </button>
      </div>

      <label className="field">
        <span>Email</span>
        <input
          type="email"
          className="form-control"
          autoComplete="email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>

      <label className="field">
        <span>Password</span>
        <div className="pw-wrap">
          <input
            type={showPw ? "text" : "password"}
            className="form-control"
            autoComplete={signup ? "new-password" : "current-password"}
            placeholder={signup ? `At least ${MIN_LENGTH} characters` : "Your password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button type="button" className="pw-toggle" onClick={() => setShowPw(!showPw)} aria-label={showPw ? "Hide passwords" : "Show passwords"}>
            {showPw ? "Hide" : "Show"}
          </button>
        </div>
        {tooShort && <small className="hint bad">Must be at least {MIN_LENGTH} characters.</small>}
      </label>

      {signup && (
        <label className="field">
          <span>Confirm password</span>
          <input
            type={showPw ? "text" : "password"}
            className={`form-control ${mismatch ? "is-bad" : matches ? "is-good" : ""}`}
            autoComplete="new-password"
            placeholder="Re-enter your password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          {mismatch && <small className="hint bad">Passwords do not match.</small>}
          {matches && <small className="hint good">Passwords match.</small>}
        </label>
      )}

      {error && <div className="auth-error" role="alert">{error}</div>}

      <button type="submit" className="btn btn-primary w-100" disabled={!canSubmit || busy}>
        {busy ? "Please wait..." : signup ? "Create account" : "Sign in"}
      </button>
    </form>
  );
}

export default AuthForm;
