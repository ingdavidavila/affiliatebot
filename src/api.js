import axios from "axios";

const API_BASE =
  process.env.NODE_ENV === "production"
    ? "https://www.affiliatesbot.com/api"
    : "http://localhost:3001/api";

/**
 * Create an axios instance with optional Authorization header
 */
function createApiClient(token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return axios.create({ baseURL: API_BASE, headers, timeout: 60000 }); // 60-second timeout per request
}

/**
 * Auth Google ID token -> backend verification
 */
export async function authGoogle(idToken) {
  const res = await axios.post(`${API_BASE}/auth/google`, { token: idToken });
  return res;
}

/**
 * Get current user info and paid status (requires token)
 */
export async function getCurrentUser(token) {
  const api = createApiClient(token);
  const res = await api.get("/me");
  return res;
}

/**
 * Create Stripe Checkout Session for a given plan ('monthly' | 'yearly')
 */
export async function createCheckoutSession(plan, token) {
  const api = createApiClient(token);
  const res = await api.post("/create-checkout-session", { plan });
  return res;
}

/**
 * Verify Stripe payment session (used after redirect)
 */
export async function verifyPayment(sessionId, token) {
  const api = createApiClient(token);
  const res = await api.post("/verify-payment", { sessionId });
  return res;
}

/**
 * Cancel an active subscription (no refund)
 */
export async function cancelSubscription(token) {
  const api = createApiClient(token);
  const res = await api.post("/cancel-subscription");
  return res;
}

/**
 * Check YouTube channel for broken links (backend runs Python) with indefinite polling
 */
export async function checkLinks(channelId, maxVideos, token, setResults, toastError) {
  const api = createApiClient(token);
  try {
    const { data } = await api.post("/check-links", { channelId, maxVideos });
    const jobId = data.jobId;

    return new Promise((resolve, reject) => {
      const checkStatus = async () => {
        try {
          const res = await api.get(`/check-links/status/${jobId}`);
          const { status, result } = res.data;
          if (status === 'completed') {
            setResults(result.brokenLinks || []);
            resolve(result.brokenLinks || []);
          } else if (status === 'failed' || status === 'error') {
            const errorMsg = result.error || 'Link check failed';
            toastError(errorMsg);
            reject(new Error(errorMsg));
          } else {
            // Continue polling
            setTimeout(checkStatus, 5000); // Poll every 5 seconds
          }
        } catch (err) {
          toastError('Unable to check link status.');
          reject(err);
        }
      };
      checkStatus();
    });
  } catch (err) {
    toastError('Unable to start the link check.');
    throw err;
  }
}

/**
 * Poll job status for check-links (optional, can be removed if checkLinks handles all)
 */
export async function getJobStatus(jobId) {
  const res = await axios.get(`${API_BASE}/check-links/status/${jobId}`);
  return res;
}