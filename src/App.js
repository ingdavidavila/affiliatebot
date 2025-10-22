import React, { useState, useEffect } from "react";
import { GoogleLogin } from "@react-oauth/google";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";
import "./App.css";
import axios from "axios";
import {
  authGoogle,
  getCurrentUser,
  createCheckoutSession,
  verifyPayment,
  checkLinks,
  getJobStatus,
  refreshSession,
} from "./api";

import AccountDropdown from "./AccountDropdown";

function App() {
  const [user, setUser] = useState(null);
  const [paid, setPaid] = useState(false);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [channelInput, setChannelInput] = useState("");
  const [showChannelPrompt, setShowChannelPrompt] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalVideos, setTotalVideos] = useState(0);

  const itemsPerPage = 10;

  /// ===== On mount, check if returning from Stripe payment =====
useEffect(() => {
  const urlParams = new URLSearchParams(window.location.search);
  const sessionId = urlParams.get("session_id");
  const token = localStorage.getItem("authToken");

  (async () => {
    // ✅ Step 1: Try to refresh token first
    if (token) {
      try {
        const refreshed = await refreshSession(token);
        localStorage.setItem("authToken", refreshed.token);
        setUser(refreshed.user);
        setPaid(refreshed.user.paid);
        setShowChannelPrompt(true);
      } catch (err) {
        console.warn("Token expired or refresh failed:", err);
        localStorage.removeItem("authToken");
      }
    }

    // ✅ Step 2: Handle Stripe return flow
    if (sessionId && token) {
      try {
        const verifyRes = await verifyPayment(sessionId, token);
        if (verifyRes.data.paid) {
          toast.success("Payment verified! Subscription active.");
          setPaid(true);
        }
      } catch (err) {
        console.error("Payment verification failed:", err);
        toast.error("Failed to verify payment.");
      } finally {
        // Clean session_id param from URL
        urlParams.delete("session_id");
        const qs = urlParams.toString();
        const cleanUrl = qs
          ? `${window.location.pathname}?${qs}`
          : window.location.pathname;
        window.history.replaceState({}, "", cleanUrl);
      }
    }
  })();
}, []);



  // ===== Handle Google Login =====
  const handleLoginSuccess = async (cred) => {
    setLoading(true);
    try {
  const response = await authGoogle(cred.credential);
const userData = response.data.user;
setUser(userData);

// ✅ Store the new JWT instead of Google ID token
localStorage.setItem("authToken", response.data.token);

  const token = response.data.token;
  const stripeCheck = await axios.get(`${process.env.REACT_APP_API_URL}/api/stripe/status`, {
  headers: { Authorization: `Bearer ${token}` },
});

  if (stripeCheck.data.paid) {
    setPaid(true);
    toast.success("Subscription active — full access unlocked!");
  } else {
    setPaid(false);
  }

  setShowChannelPrompt(true);
} catch (err) {
  console.error(err);
  toast.error("Login failed.");
} finally {
  setLoading(false);
}
  };

  const handleLogout = () => {
    setUser(null);
    setPaid(false);
    setResults([]);
    setChannelInput("");
    localStorage.removeItem("authToken");
    toast.info("Logged out.");
  };

  // ===== Handle Channel Check =====
  const handleChannelSubmit = async () => {
  if (!channelInput.trim()) {
    toast.error("Please enter a Channel ID.");
    return;
  }

  setLoading(true);
  setResults([]); // clear old results
  setError("");
  const token = localStorage.getItem("authToken");

  try {
    // Step 1: Start the background job
    const startRes = await checkLinks(channelInput, paid ? -1 : 50, token);
    const jobId = startRes.data.jobId;
    toast.info("Checking links... this may take up to a minute.");

    // Step 2: Poll every 4 seconds for job completion
    const pollInterval = 4000;
    const timeout = 360000; // 3 minutes
    const startTime = Date.now();

    const poll = setInterval(async () => {
  try {
    const res = await getJobStatus(jobId);
    if (res.data.status === "completed") {
      clearInterval(poll);
      const brokenLinks = res.data.result.brokenLinks || [];
      const total = res.data.result.totalVideos || 0;
      setResults(brokenLinks);
      setTotalVideos(total);
      if (brokenLinks.length === 0) {
    toast.success("✅ No broken links found!");
    setShowChannelPrompt(false);
    setLoading(false);
    return;
    }
      if (paid) {
  toast.success(`✅ Completed — checked all your videos.`);
} else {
  toast.info("✅ Checked your first 50 videos. Want to scan the rest?", {
    autoClose: 5000,
  });

  // 👇 Force the paywall to show
  setPaid(false);
  
  // 👇 Smooth scroll to the paywall section
  setTimeout(() => {
    const paywallSection = document.getElementById("paywall-section");
    if (paywallSection) {
      paywallSection.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, 800);
}

      setLoading(false);
    } else if (res.data.status === "error") {
      clearInterval(poll);
      toast.error("Something went wrong while checking links.");
      setLoading(false);
    } 
    // 🕒 Extended timeout with one last grace check
    else if (Date.now() - startTime > timeout) {
      const finalRes = await getJobStatus(jobId);
      if (finalRes.data.status === "completed") {
        clearInterval(poll);
        const brokenLinks = finalRes.data.result.brokenLinks || [];
        const total = finalRes.data.result.totalVideos || 0;
        setResults(brokenLinks);
        setTotalVideos(total);
        toast.success(
          `Completed — checked ${paid ? "all" : "first 50"} videos.`
        );
      } else {
        clearInterval(poll);
        toast.error("Timed out waiting for link check to complete.");
      }
      setLoading(false);
    }
  } catch (err) {
    clearInterval(poll);
    toast.error("Polling failed — please try again.");
    setLoading(false);
  }
}, pollInterval);

  } catch (err) {
    console.error("Error starting link check:", err);
    toast.error("Unable to start the link check.");
    setLoading(false);
  }
};


  // ===== Stripe Payment Redirect =====
  const handleSubscribe = async (plan) => {
    try {
      const token = localStorage.getItem("authToken");
      const res = await createCheckoutSession(plan, token);
      window.location.href = res.data.url; // redirect to Stripe Checkout
    } catch (err) {
      console.error(err);
      toast.error("Payment setup failed.");
    }
  };

  // ===== Pagination =====
  const indexOfLastItem = currentPage * itemsPerPage;
  const indexOfFirstItem = indexOfLastItem - itemsPerPage;
  const currentResults = results.slice(indexOfFirstItem, indexOfLastItem);
  const totalPages = Math.ceil(results.length / itemsPerPage);
  const paginate = (page) => setCurrentPage(page);

  // ===== Paywall condition =====
  const shouldShowPaywall =
   !paid && ((results.length > 0) || (results.length === 0 && totalVideos > 50));

  return (
    <div className="app-wrapper">
      <ToastContainer position="top-right" autoClose={4000} />
      <div className="container mt-4">
        {/* Account Dropdown (only for paid users) */}
        {user && paid && (
          <div style={{ position: "absolute", top: 10, left: 10 }}>
            <AccountDropdown user={user} onLogout={handleLogout} />
          </div>
        )}

        <div className="card p-4 shadow">
          <h1 className="text-center mb-3">AffiliateBot</h1>

          {!user ? (
            <div className="text-center">
              <p>Sign in to start checking your YouTube affiliate links.</p>
              <GoogleLogin
                onSuccess={handleLoginSuccess}
                onError={() => toast.error("Google login failed.")}
                scope="https://www.googleapis.com/auth/youtube.readonly"
                text="signin_with"
              />
            </div>
          ) : (
            <div className="text-center">
              <p>Logged in as {user.email}</p>
              <button className="btn btn-outline-danger" onClick={handleLogout}>
                Log Out
              </button>
            </div>
          )}

          {user && showChannelPrompt && (
            <div className="mt-4">
              <h5>Enter Your YouTube Channel ID</h5>
          <p className="text-muted small mb-2">
            You can find your Channel ID by visiting{" "}
            <a
    href="https://support.google.com/youtube/answer/3250431?hl=en"
    target="_blank"
    rel="noopener noreferrer"
  >
    Find your Channel Id.
  </a>{" "}
          </p>

<input
  type="text"
  className="form-control mb-2"
  placeholder="(e.g. UC1234567890ABCDE)"
  value={channelInput}
  onChange={(e) => setChannelInput(e.target.value)}
/>

              <button
                className="btn btn-primary"
                onClick={handleChannelSubmit}
                disabled={loading}
              >
                {loading ? "Checking..." : "Check Links"}
              </button>
            </div>
          )}

          {results.length > 0 && !shouldShowPaywall && (
            <div className="mt-4">
              <h5>Broken Links</h5>
              <table className="table table-striped">
                <thead>
                  <tr>
                    <th>Video</th>
                    <th>Broken Link</th>
                  </tr>
                </thead>
                <tbody>
                  {currentResults.map((r, i) => (
                    <tr key={i}>
                      <td>
                        <a
                          href={`https://www.youtube.com/watch?v=${r.videoId}`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          View Video
                        </a>
                      </td>
                      <td style={{ wordBreak: "break-all" }}>
                        <a
                          href={r.link}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {r.link}
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {totalPages > 1 && (
                <div className="text-center mt-3">
                  <button
                    className="btn btn-secondary me-2"
                    disabled={currentPage === 1}
                    onClick={() => paginate(currentPage - 1)}
                  >
                    Prev
                  </button>
                  <span>
                    Page {currentPage} of {totalPages}
                  </span>
                  <button
                    className="btn btn-secondary ms-2"
                    disabled={currentPage === totalPages}
                    onClick={() => paginate(currentPage + 1)}
                  >
                    Next
                  </button>
                </div>
              )}
            </div>
          )}

          {shouldShowPaywall && (
            <div id="paywall-section" className="text-center mt-4">
              <h5>Unlock Full Access</h5>
              <p>
                Subscribe to view all broken links and check every video on your
                channel.
              </p>
              <div>
                <button
                  className="btn btn-outline-success"
                  onClick={() => handleSubscribe("monthly")}
                >
                  $14.99 / month
                </button>
                <button
                  className="btn btn-outline-success"
                  onClick={() => handleSubscribe("yearly")}
                >
                  $99.99 / year
                </button>
              </div>
            </div>
          )}
        </div>

        <footer className="text-center text-muted mt-4 mb-3">
          Made by{" "}
          <a
            href="https://workingrobotsinc.com"
            target="_blank"
            rel="noopener noreferrer"
          >
            WorkingRobots Inc.
          </a>
          
        </footer>
      </div>
    </div>
  );
}

export default App;
