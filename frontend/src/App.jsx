import { useCallback, useEffect, useState } from "react";

import ReactMarkdown from "react-markdown";

import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const PENDING_PR_KEY = "reviewpilot.pendingPR";

function isValidPrUrl(value) {

  try {

    const parsed = new URL(value.trim());

    return (

      parsed.hostname.toLowerCase() === "github.com" &&

      /^\/[^/]+\/[^/]+\/pull\/\d+\/?$/.test(parsed.pathname)

    );

  } catch {

    return false;

  }

}


function getInstallationSettingsUrl(item) {
  const account = encodeURIComponent(item.account);

  if (item.target_type?.toLowerCase() === "organization") {
    return `https://github.com/organizations/${account}/settings/installations/${item.id}`;
  }

  return `https://github.com/settings/installations/${item.id}`;
}


async function apiRequest(path, options = {}) {

  const response = await fetch(`${API}${path}`, {

    credentials: "include",

    ...options,

    headers: {

      ...(options.body ? { "Content-Type": "application/json" } : {}),

      ...(options.headers || {}),

    },

  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {

    const detail = data.detail;

    const message =

      typeof detail === "string"

        ? detail

        : detail?.message || `Request failed (${response.status})`;

    const error = new Error(message);

    error.status = response.status;

    error.data = data;

    throw error;

  }

  return data;

}

export default function App() {

  const [url, setUrl] = useState("");

  const [res, setRes] = useState(null);

  const [err, setErr] = useState("");

  const [notice, setNotice] = useState("");

  const [busy, setBusy] = useState(false);

  const [user, setUser] = useState(null);

  const [authLoading, setAuthLoading] = useState(true);

  const [installations, setInstallations] = useState([]);

  const [installationId, setInstallationId] = useState("");

  const [repositories, setRepositories] = useState([]);

  const [repository, setRepository] = useState("");

  const [connectionLoading, setConnectionLoading] = useState(false);

  const [availableInstallations, setAvailableInstallations] = useState([]);
const [connectingInstallationId, setConnectingInstallationId] = useState("");

  const loadInstallations = useCallback(async () => {

    const data = await apiRequest("/auth/installations");

    const items = data.installations || [];

    setInstallations(items);

    setInstallationId((currentId) => {

      if (items.length === 1) return String(items[0].id);

      if (items.some((item) => String(item.id) === currentId)) return currentId;

      return "";

    });

    return items;

  }, []);

  const loadAvailableInstallations = useCallback(async () => {
  const data = await apiRequest("/auth/available-installations");
  setAvailableInstallations(data.installations || []);
}, []);

  
const loadUser = useCallback(async () => {
  setAuthLoading(true);

  try {
    const data = await apiRequest("/auth/me");
    setUser(data.user || null);

    const results = await Promise.allSettled([
      loadInstallations(),
      loadAvailableInstallations(),
    ]);

    results.forEach((result, index) => {
      if (result.status === "rejected") {
        console.error(
          index === 0
            ? "Failed to load connected installations:"
            : "Failed to load available installations:",
          result.reason
        );
      }
    });
  } catch (error) {
    console.error("Failed to load GitHub user:", error);

    setUser(null);
    setInstallations([]);
    setRepositories([]);
    setInstallationId("");
    setRepository("");
  } finally {
    setAuthLoading(false);
  }
}, [loadInstallations, loadAvailableInstallations]);

  async function connectExistingInstallation(id) {
  setConnectingInstallationId(String(id));
  setErr("");

  try {
    await apiRequest("/auth/connect-installation", {
      method: "POST",
      body: JSON.stringify({ installation_id: Number(id) }),
    });

    await loadInstallations();
    await loadAvailableInstallations();
    setNotice("GitHub installation connected successfully.");
  } catch (error) {
    setErr(error.message || "Could not connect this installation.");
  } finally {
    setConnectingInstallationId("");
  }
}

  
useEffect(() => {
  const refreshAccess = () => {
    if (document.visibilityState === "visible" && user) {
      loadInstallations().catch((error) => {
        setErr(error.message || "Could not refresh GitHub installations.");
      });
    }
  };

  window.addEventListener("focus", refreshAccess);
  document.addEventListener("visibilitychange", refreshAccess);

  return () => {
    window.removeEventListener("focus", refreshAccess);
    document.removeEventListener("visibilitychange", refreshAccess);
  };
}, [user, loadInstallations]);


  useEffect(() => {

    const savedPr = window.sessionStorage.getItem(PENDING_PR_KEY);

    if (savedPr && isValidPrUrl(savedPr)) {

      setUrl(savedPr);

    }

    const params = new URLSearchParams(window.location.search);

    const githubStatus = params.get("github");

    const authError = params.get("auth_error");

    const resumePr = params.get("resume_pr");

    if (resumePr && isValidPrUrl(resumePr)) {

      window.sessionStorage.setItem(PENDING_PR_KEY, resumePr);

      window.sessionStorage.setItem("reviewpilot.autoResume", resumePr);

      setUrl(resumePr);

      setNotice("GitHub authorization completed. Resuming your pull request review…");

      window.history.replaceState({}, document.title, window.location.pathname);

      // Defer until the session cookie is set and /auth/me can be checked.

      window.setTimeout(() => {

        window.dispatchEvent(new Event("reviewpilot:resume-review"));

      }, 0);

    } else if (githubStatus === "connected") {

      setNotice("GitHub authorization completed. You can continue with your pull request.");

    } else if (authError) {

      setErr(`GitHub authorization failed: ${authError.replaceAll("_", " ")}`);

    }

    if (!resumePr && (githubStatus || authError)) {

      window.history.replaceState({}, document.title, window.location.pathname);

    }

    loadUser();

  }, [loadUser]);

  
useEffect(() => {
  function handleGitHubOAuthMessage(event) {
    if (event.origin !== window.location.origin) return;

    if (
      event.data?.type === "reviewpilot-github-oauth" &&
      event.data?.status === "account_added"
    ) {
      loadUser();
      loadInstallations();
    }
  }

  window.addEventListener("message", handleGitHubOAuthMessage);
  return () => {
    window.removeEventListener("message", handleGitHubOAuthMessage);
  };
}, [loadUser, loadInstallations]);


  useEffect(() => {

    const resume = async () => {

      const pending = window.sessionStorage.getItem(PENDING_PR_KEY);

      if (!pending || !isValidPrUrl(pending)) return;

      try {

        await apiRequest("/auth/me");

      } catch {

        return;

      }

      // Only auto-run after GitHub returns with resume_pr, not on every page load.

      const marker = window.sessionStorage.getItem("reviewpilot.autoResume");

      if (marker !== pending) return;

      window.sessionStorage.removeItem("reviewpilot.autoResume");

      setUrl(pending);

      setBusy(true);

      setErr("");

      setNotice("");

      setRes(null);

      try {

        const result = await apiRequest("/review", {

          method: "POST",

          body: JSON.stringify({ pr_url: pending }),

        });

        setRes(result);

        window.sessionStorage.removeItem(PENDING_PR_KEY);

      } catch (error) {

        setErr(error.message || "The pull request review failed.");

        if (error.status === 401 || error.status === 403) {

          setNotice("GitHub returned you to ReviewPilot, but this repository still isn't accessible. Check that you selected the repository during installation and granted the requested permissions.");

        }

      } finally {

        setBusy(false);

      }

    };

    const handler = () => {

      const pending = window.sessionStorage.getItem(PENDING_PR_KEY);

      if (pending) window.sessionStorage.setItem("reviewpilot.autoResume", pending);

      resume();

    };

    window.addEventListener("reviewpilot:resume-review", handler);

    return () => window.removeEventListener("reviewpilot:resume-review", handler);

  }, []);

  useEffect(() => {

    if (!user || !installationId) {

      setRepositories([]);

      setRepository("");

      return undefined;

    }

    let cancelled = false;

    async function loadRepos() {

      setConnectionLoading(true);

      setErr("");

      try {

        const data = await apiRequest(

          `/auth/repositories?installation_id=${encodeURIComponent(installationId)}`

        );

        if (!cancelled) {

          const items = data.repositories || [];

          setRepositories(items);

          setRepository((currentRepository) => {

            if (items.some((item) => item.full_name === currentRepository)) {

              return currentRepository;

            }

            return items.length === 1 ? items[0].full_name : "";

          });

        }

      } catch (error) {

        if (!cancelled) {

          setRepositories([]);

          setRepository("");

          setErr(error.message || "Could not load repositories.");

        }

      } finally {

        if (!cancelled) setConnectionLoading(false);

      }

    }

    loadRepos();

    return () => {

      cancelled = true;

    };

  }, [user, installationId]);

  function preservePendingPr() {

    const candidate = url.trim();

    if (isValidPrUrl(candidate)) {

      window.sessionStorage.setItem(PENDING_PR_KEY, candidate);

    }

  }

  function signIn() {

    preservePendingPr();

    const prUrl = isValidPrUrl(url.trim()) ? url.trim() : "";

    // /auth/connect starts OAuth when needed, then continues to GitHub App installation.

    const query = prUrl ? `?pr_url=${encodeURIComponent(prUrl)}` : "";

    window.location.assign(`${API}/auth/connect${query}`);

  }

  function connectRepositories() {

    preservePendingPr();

    const prUrl = isValidPrUrl(url.trim()) ? url.trim() : "";

    const query = prUrl ? `?pr_url=${encodeURIComponent(prUrl)}` : "";

    window.location.assign(`${API}/auth/connect${query}`);

  }

  async function signOut() {

    setErr("");

    setNotice("");

    try {

      await apiRequest("/auth/logout", { method: "POST" });

    } catch (error) {

      setErr(error.message || "Could not sign out.");

    } finally {

      setUser(null);

      setInstallations([]);

      setInstallationId("");

      setRepositories([]);

      setRepository("");

      setRes(null);

    }

  }

  async function run() {

    const prUrl = url.trim();

    if (!prUrl) {

      setErr("Enter a GitHub pull request URL.");

      return;

    }

    if (!isValidPrUrl(prUrl)) {

      setErr(

        "Enter a valid GitHub pull request URL, such as https://github.com/owner/repository/pull/123."

      );

      return;

    }

    setBusy(true);

    setErr("");

    setNotice("");

    setRes(null);

    window.sessionStorage.setItem(PENDING_PR_KEY, prUrl);

    try {

      const data = await apiRequest("/review", {

        method: "POST",

        body: JSON.stringify({ pr_url: prUrl }),

      });

      setRes(data);

      window.sessionStorage.removeItem(PENDING_PR_KEY);

    } catch (error) {

      setErr(error.message || "The pull request review failed.");

      if (error.status === 401 || error.status === 403 || error.status === 404) {

        setNotice(

          "This pull request may be private or ReviewPilot may not have repository access. Authorize GitHub access and select this repository to continue."

        );

      }

    } finally {

      setBusy(false);

    }

  }

  function handleRepositoryChange(value) {

    setRepository(value);

    if (!value) return;

    const match = url.match(/\/pull\/(\d+)/);

    if (match) {

      setUrl(`https://github.com/${value}/pull/${match[1]}`);

    }

  }

  return (

    <div className="app">

      <div className="background-glow glow-one"></div>

      <div className="background-glow glow-two"></div>

      <nav className="navbar">

        <div className="brand">

          <div className="brand-icon">R</div>

          <div>

            <div className="brand-name">ReviewPilot</div>

            <div className="brand-subtitle">AI Code Review</div>

          </div>

        </div>

        <div className="nav-actions">

          <div className="nav-status">

            <span className="status-dot"></span>

            AI Review Engine

          </div>

          {authLoading ? (

            <span className="auth-status">Checking GitHub…</span>

          ) : user ? (

            <div className="github-user">
  <button className="auth-button secondary" onClick={signOut}>
    Sign out
  </button>
</div>

          ) : (

            <button className="auth-button" onClick={signIn}>

              <span aria-hidden="true">●</span> Sign in with GitHub

            </button>

          )}

        </div>

      </nav>

      <main className="container">

        <section className="hero">

          <div className="hero-badge">

            <span>✦</span>

            Powered by AI

          </div>

          <h1>

            Smarter code reviews,

            <span> automatically.</span>

          </h1>

          <p>

            Paste a public or private GitHub Pull Request. If access is needed,

            ReviewPilot guides you through GitHub authorization and repository installation.

          </p>

        </section>

        {user && (

          <section className="review-card connection-card">

            <div className="card-header">

              {/* <div>

                <h2>Connect a repository</h2>

                {availableInstallations.length > 0 && (
  <div className="input-group">
    <label>Existing installations available to connect</label>

    {availableInstallations.map((item) => (
      <div
        key={item.id}
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "12px",
          marginTop: "10px",
        }}
      >
        <span>
          {item.account} ({item.target_type})
        </span>

        <button
          type="button"
          className="auth-button secondary"
          disabled={Boolean(connectingInstallationId)}
          onClick={() => connectExistingInstallation(item.id)}
        >
          {connectingInstallationId === String(item.id)
            ? "Connecting…"
            : "Connect"}
        </button>
      </div>
    ))}
  </div>
)}

                <p>

                  Choose a GitHub App installation to view the repositories it

                  has permission to access.

                </p>

              </div> */}

             {/*  <div className="github-badge">GitHub connected</div> */}

            </div>

            <div
  style={{
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: "12px",
    flexWrap: "wrap",
    marginBottom: "12px",
  }}
>
  <h3 style={{ margin: 0, fontSize: "15px" }}>
    Connected GitHub accounts
  </h3>

  <button onClick={() => {
    window.location.href = `${API}/auth/github/add-account`;
  }} 
  className="connect-another-account-button">
    Connect another GitHub account
  </button>
              {installations.length > 0 ? (
                <div style={{
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    width: "100%",
    alignItems: "stretch",
    boxSizing: "border-box",
  }}>
                  {installations.map((item) => (
                    <div
                      key={item.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "12px",
                        padding: "12px",
                        border: "1px solid rgba(148, 163, 184, 0.14)",
                        borderRadius: "10px",
                      }}
                    >
                     
<div className="connected-account-avatar" aria-hidden="true">
  <svg
    viewBox="0 0 24 24"
    width="23"
    height="23"
    fill="currentColor"
  >
    <path d="M12 .8a11.2 11.2 0 0 0-3.54 21.83c.56.1.77-.24.77-.54v-2.1c-3.14.68-3.8-1.33-3.8-1.33-.5-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.69.08-.69 1.13.08 1.73 1.16 1.73 1.16 1 .1.75 2.04 3.04 1.57.1-.73.4-1.22.72-1.5-2.5-.28-5.13-1.25-5.13-5.56 0-1.23.44-2.23 1.16-3.02-.12-.29-.5-1.43.11-2.98 0 0 .95-.3 3.08 1.15a10.7 10.7 0 0 1 5.6 0c2.14-1.45 3.08-1.15 3.08-1.15.61 1.55.23 2.69.12 2.98.72.79 1.15 1.79 1.15 3.02 0 4.32-2.63 5.27-5.14 5.55.4.35.77 1.03.77 2.08v3.08c0 .3.2.65.78.54A11.2 11.2 0 0 0 12 .8Z" />
  </svg>
</div>

                      <div style={{ display: "flex", flex: 1, flexDirection: "column", gap: "4px", minWidth: "180px" }}>
                        <strong style={{ overflowWrap: "anywhere", fontSize: "14px" }}>
                          {item.account}
                        </strong>
                        <span style={{ color: "#94a3b8", fontSize: "12px" }}>
                          GitHub {item.target_type}
                        </span>
                      </div>
                      
<div
  style={{
    display: "flex",
    alignItems: "center",
    gap: "10px",
    flexWrap: "wrap",
  }}
>
  <span
    style={{
      color: "#86efac",
      fontSize: "12px",
      whiteSpace: "nowrap",
    }}
  >
    Connected
  </span>

  

<button
  type="button"
  className="auth-button secondary"
  onClick={() => {
    window.open(
      getInstallationSettingsUrl(item),
      "_blank",
      "noopener,noreferrer"
    );
  }}
>
  Manage Repo Access / Uninstall ReviewPilot
</button>


</div>

                    </div>
                  ))}
                </div>
              ) : (
                <p>No GitHub App installations are connected to this session yet.</p>
              )}
            </div>

            {installations.length === 0 ? (

              <div className="connection-empty">

                <p>

                  ReviewPilot is not installed on an account available to this

                  session yet. Install it on the GitHub account or organization

                  that owns the repository you want to review.

                </p>

                <button className="review-button" onClick={connectRepositories}>

                  Connect repositories <span className="arrow">→</span>

                </button>

              </div>

            ) : (

              <>

                <div className="input-group">

                  <label htmlFor="installation-select">GitHub account</label>

                  <select

                    id="installation-select"

                    value={installationId}

                    onChange={(event) => setInstallationId(event.target.value)}

                    disabled={connectionLoading}

                  >

                    <option value="">Select an installation</option>

                    {installations.map((item) => (

                      <option key={item.id} value={item.id}>

                        {item.account} ({item.target_type})

                      </option>

                    ))}

                  </select>

                </div>

                {installationId && (

                  <div className="input-group">

                    <label htmlFor="repository-select">Repository</label>

                    <select

                      id="repository-select"

                      value={repository}

                      onChange={(event) =>

                        handleRepositoryChange(event.target.value)

                      }

                      disabled={connectionLoading || repositories.length === 0}

                    >

                      <option value="">

                        {connectionLoading

                          ? "Loading repositories…"

                          : "Select a repository"}

                      </option>

                      {repositories.map((item) => (

                        <option key={item.full_name} value={item.full_name}>

                          {item.full_name}

                          {item.private ? " (private)" : ""}

                        </option>

                      ))}

                    </select>

                    {repositories.length === 0 && !connectionLoading && (

                      <p className="field-help">

                        No repositories were returned for this installation.

                        Check the App installation and repository permissions.

                      </p>

                    )}

                  </div>

                )}

                <button

                  className="auth-button secondary"

                  onClick={connectRepositories}

                >

                  Manage / add repositories on GitHub

                </button>

              </>

            )}

          </section>

        )}

        <section className="review-card">

          <div className="card-header">

            <div>

              <h2>Review a Pull Request</h2>

              <p>

                {repository

                  ? `Selected repository: ${repository}`

                  : "Enter a GitHub PR URL to start an automated review."}

              </p>

            </div>

            <div className="github-badge">

              <span>●</span> GitHub

            </div>

          </div>

          <div className="input-group">

            <label htmlFor="pr-url">Pull Request URL</label>

            <div className="url-input-wrapper">

              <div className="url-icon">↗</div>

              <input

                id="pr-url"

                value={url}

                onChange={(event) => setUrl(event.target.value)}

                placeholder="https://github.com/owner/repository/pull/123"

                disabled={busy}

                onKeyDown={(event) => {

                  if (event.key === "Enter" && !busy) run();

                }}

              />

            </div>

          </div>

          <button

            className="review-button"

            onClick={run}

            disabled={busy || !url.trim()}

          >

            {busy ? (

              <>

                <span className="spinner"></span>

                Analyzing Pull Request…

              </>

            ) : (

              <>

                Review Pull Request <span className="arrow">→</span>

              </>

            )}

          </button>

          <div className="security-note">

            <span>🔒</span>

            Public PRs can be reviewed without signing in. Private PRs require

            the GitHub App to be installed on the repository.

          </div>

        </section>

        {notice && (

          <div className="connection-empty" role="status">

            <p>{notice}</p>

            <button className="review-button" onClick={connectRepositories}>

              Authorize GitHub access <span className="arrow">→</span>

            </button>

          </div>

        )}

        {err && (

          <div className="error-card" role="alert">

            <div className="error-icon">!</div>

            <div>

              <strong>Request failed</strong>

              <p>{err}</p>

            </div>

          </div>

        )}

        {busy && (

          <div className="loading-card" aria-live="polite">

            <div className="loading-animation">

              <span></span>

              <span></span>

              <span></span>

            </div>

            <div>

              <strong>ReviewPilot is analyzing your PR</strong>

              <p>Fetching changes and running the AI review pipeline…</p>

            </div>

          </div>

        )}

        {res && !busy && (

          <section className="results">

            <div className="results-header">

              <div>

                <div className="results-label">REVIEW COMPLETE</div>

                <h2>Pull Request Analysis</h2>

                <p>Review generated successfully by ReviewPilot.</p>

              </div>

              <div className="success-badge">✓ Complete</div>

            </div>

            <ReviewSection

              number="01"

              title="Summary"

              description="What this pull request changes"

              icon="⌁"

              className="summary-section"

              content={res.plan}

            />

            <ReviewSection

              number="02"

              title="Code Review"

              description="Potential bugs, security issues and improvements"

              icon="◈"

              className="review-section"

              content={res.review}

            />

            <ReviewSection

              number="03"

              title="Suggested Tests"

              description="Recommended unit and integration tests"

              icon="✓"

              className="tests-section"

              content={res.tests}

            />

          </section>

        )}

        {!res && !busy && (

          <section className="features">

            <Feature

              icon="⌁"

              title="AI-Powered Analysis"

              text="Uses an LLM to understand code changes and identify risky areas."

            />

            <Feature

              icon="◈"

              title="Security Aware"

              text="Sensitive credentials are redacted before code reaches the AI."

            />

            <Feature

              icon="✓"

              title="Actionable Tests"

              text="Get concrete test cases based on the actual changes."

            />

          </section>

        )}

      </main>

      <footer>

        <span>ReviewPilot</span>

        <span>•</span>

        <span>AI-powered GitHub code reviews</span>

      </footer>

    </div>

  );

}

function ReviewSection({

  number,

  title,

  description,

  icon,

  content,

  className = "",

}) {

  return (

    <article className={`result-card ${className}`}>

      <div className="result-card-top">

        <div className="result-icon">{icon}</div>

        <div className="result-heading">

          <div className="result-number">{number}</div>

          <div>

            <h3>{title}</h3>

            <p>{description}</p>

          </div>

        </div>

      </div>

      <div className="markdown-content">

        <ReactMarkdown>{content || ""}</ReactMarkdown>

      </div>

    </article>

  );

}

function Feature({ icon, title, text }) {

  return (

    <div className="feature">

      <div className="feature-icon">{icon}</div>

      <div>

        <h3>{title}</h3>

        <p>{text}</p>

      </div>

    </div>

  );

}
