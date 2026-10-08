import { useState } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  const [url, setUrl] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const [showTokenPopup, setShowTokenPopup] = useState(false);
  const [githubToken, setGithubToken] = useState("");

  async function run(token = null) {
    setBusy(true);
    setErr("");
    setRes(null);

    try {
      const body = {
        pr_url: url,
      };

      if (token) {
        body.github_token = token;
      }

      const r = await fetch(`${API}/review`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });

      const data = await r.json();

      if (!r.ok) {
        if (
          r.status === 403 &&
          !token &&
          data.detail?.includes("not publicly accessible")
        ) {
          setShowTokenPopup(true);
          return;
        }

        throw new Error(data.detail || r.statusText);
      }

      setRes(data);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function runWithToken() {
    if (!githubToken.trim()) {
      setErr("Please enter a GitHub token.");
      return;
    }

    setShowTokenPopup(false);
    await run(githubToken.trim());
    setGithubToken("");
  }

  return (
    <div className="app">

      {/* Background */}
      <div className="background-glow glow-one"></div>
      <div className="background-glow glow-two"></div>

      {/* Navbar */}
      <nav className="navbar">
        <div className="brand">
          <div className="brand-icon">R</div>

          <div>
            <div className="brand-name">ReviewPilot</div>
            <div className="brand-subtitle">AI Code Review</div>
          </div>
        </div>

        <div className="nav-status">
          <span className="status-dot"></span>
          AI Review Engine
        </div>
      </nav>

      {/* Main */}
      <main className="container">

        {/* Hero */}
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
            Paste a GitHub Pull Request and let ReviewPilot analyze the
            changes, identify potential issues, and suggest tests.
          </p>

        </section>

        {/* Review Card */}
        <section className="review-card">

          <div className="card-header">
            <div>
              <h2>Review a Pull Request</h2>
              <p>
                Enter a GitHub PR URL to start an automated review.
              </p>
            </div>

            <div className="github-badge">
              <span>●</span> GitHub
            </div>
          </div>

          <div className="input-group">

            <label>Pull Request URL</label>

            <div className="url-input-wrapper">

              <div className="url-icon">
                ↗
              </div>

              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://github.com/owner/repository/pull/123"
                disabled={busy}
              />

            </div>

          </div>

          <button
            className="review-button"
            onClick={() => run()}
            disabled={busy || !url.trim()}
          >

            {busy ? (
              <>
                <span className="spinner"></span>
                Analyzing Pull Request...
              </>
            ) : (
              <>
                Review Pull Request
                <span className="arrow">→</span>
              </>
            )}

          </button>

          <div className="security-note">
            <span>🔒</span>
            Public PRs require no GitHub token.
            Private repositories use a request-scoped token.
          </div>

        </section>

        {/* Error */}
        {err && (
          <div className="error-card">
            <div className="error-icon">!</div>

            <div>
              <strong>Review failed</strong>
              <p>{err}</p>
            </div>
          </div>
        )}

        {/* Loading */}
        {busy && (
          <div className="loading-card">

            <div className="loading-animation">
              <span></span>
              <span></span>
              <span></span>
            </div>

            <div>
              <strong>ReviewPilot is analyzing your PR</strong>
              <p>
                Fetching changes and running the AI review pipeline...
              </p>
            </div>

          </div>
        )}

        {/* Results */}
        {res && !busy && (
          <section className="results">

            <div className="results-header">

              <div>
                <div className="results-label">
                  REVIEW COMPLETE
                </div>

                <h2>Pull Request Analysis</h2>

                <p>
                  Review generated successfully by ReviewPilot.
                </p>
              </div>

              <div className="success-badge">
                ✓ Complete
              </div>

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

        {/* Features */}
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

      {/* Footer */}
      <footer>
        <span>ReviewPilot</span>
        <span>•</span>
        <span>AI-powered GitHub code reviews</span>
      </footer>

      {/* Private Repository Modal */}
      {showTokenPopup && (
        <div className="modal-overlay">

          <div className="token-modal">

            <button
              className="modal-close"
              onClick={() => {
                setShowTokenPopup(false);
                setGithubToken("");
              }}
            >
              ×
            </button>

            <div className="private-icon">
              🔐
            </div>

            <div className="modal-label">
              PRIVATE REPOSITORY
            </div>

            <h2>GitHub access required</h2>

            <p className="modal-description">
              This Pull Request isn't publicly accessible. Provide a
              GitHub Personal Access Token that has access to this
              repository.
            </p>

            <div className="permissions">

              <div className="permission-title">
                Required permissions
              </div>

              <div className="permission">
                <span>✓</span>
                Pull requests — Read
              </div>

              <div className="permission">
                <span>✓</span>
                Contents — Read-only
              </div>

              <div className="permission">
                <span>✓</span>
                Metadata — Read-only
              </div>

            </div>

            <label className="token-label">
              GitHub Personal Access Token
            </label>

            <input
              className="token-input"
              type="password"
              value={githubToken}
              onChange={(e) => setGithubToken(e.target.value)}
              placeholder="github_pat_..."
            />

            <div className="token-warning">
              🔒 Your token is used only for this request and is not
              stored by ReviewPilot.
            </div>

            <button
              className="token-button"
              onClick={runWithToken}
            >
              Continue with Token
              <span>→</span>
            </button>

            <button
              className="cancel-button"
              onClick={() => {
                setShowTokenPopup(false);
                setGithubToken("");
              }}
            >
              Cancel
            </button>

          </div>

        </div>
      )}

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

        <div className="result-icon">
          {icon}
        </div>

        <div className="result-heading">

          <div className="result-number">
            {number}
          </div>

          <div>
            <h3>{title}</h3>
            <p>{description}</p>
          </div>

        </div>

      </div>

      <div className="markdown-content">
        <ReactMarkdown>
          {content}
        </ReactMarkdown>
      </div>

    </article>
  );
}


function Feature({ icon, title, text }) {
  return (
    <div className="feature">

      <div className="feature-icon">
        {icon}
      </div>

      <div>
        <h3>{title}</h3>
        <p>{text}</p>
      </div>

    </div>
  );
}