require('dotenv').config();
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

  // ===== On mount, check if returning from Stripe payment =====
  // ===== On mount, check if returning from Stripe payment =====
useEffect(() => {
  const urlParams = new URLSearchParams(window.location.search);
  const sessionId = urlParams.get("session_id");
  const token = localStorage.getItem("authToken");

  (async () => {
    // Rehydrate user if token exists
    if (token) {
      try {
        const res = await getCurrentUser(token);
        setUser({ email: res.data.email });
        setPaid(res.data.paid);
        setShowChannelPrompt(true);
      } catch (err) {
        console.error("Failed to fetch user:", err);
      }
    }

    // Handle Stripe return flow
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
  const userData = response.data.user || response.data;
  setUser(userData);
  localStorage.setItem("authToken", cred.credential);

  // Immediately check Stripe status after login
  const stripeCheck = await axios.get(`${process.env.FRONTEND_URL}/api/stripe/status`, {
    headers: { Authorization: `Bearer ${cred.credential}` },
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
    const timeout = 180000; // 3 minutes
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
          toast.success(
            `Completed — checked ${paid ? "all" : "first 50"} videos.`
          );
          setLoading(false);
        } else if (res.data.status === "error") {
          clearInterval(poll);
          toast.error("Something went wrong while checking links.");
          setLoading(false);
        } else if (Date.now() - startTime > timeout) {
          clearInterval(poll);
          toast.error("Timed out waiting for link check to complete.");
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
              <input
                type="text"
                className="form-control mb-2"
                placeholder="e.g. UC1234567890"
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
            <div className="text-center mt-4">
              <h5>Unlock Full Access</h5>
              <p>
                Subscribe to view all broken links and check every video on your
                channel.
              </p>
              <div>
                <button
                  className="btn btn-success me-2"
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
