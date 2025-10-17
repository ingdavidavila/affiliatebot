import axios from 'axios';

// ✅ Automatically detect correct API base URL
const API_BASE_URL =
  process.env.NODE_ENV === 'production'
    ? 'https://www.affiliatesbot.com/api'
    : 'http://localhost:3001/api';

// ✅ Use one consistent Axios instance
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 35000,
});

// --- API functions ---

export const verifyPayment = async (
  sessionId,
  setLoading,
  setPaid,
  setShowChannelPrompt,
  setChannelInput,
  user,
  toastError
) => {
  setLoading(true);
  try {
    const { data } = await api.post('/verify-payment', { sessionId });
    setPaid(data.paid);
    if (data.paid && user) {
      setShowChannelPrompt(true);
      setChannelInput(user.lastChannelId || '');
    }
  } catch (err) {
    toastError('Something went wrong while verifying your payment.');
  } finally {
    setLoading(false);
  }
};

export const authGoogle = async (token) => {
  return await api.post('/auth/google', { token });
};

export const getUserStatus = async (email) => {
  return await api.get(`/user-status?email=${email}`);
};

// ✅ Fixed version — uses API_BASE_URL consistently and resolves properly
export const checkLinks = async (channelId, maxVideos, setResults, toastError) => {
  try {
    // Step 1: Start background job
    const { data } = await api.post('/check-links', { channelId, maxVideos });
    const jobId = data.jobId;

    // Step 2: Poll every 3 seconds until done
    return new Promise((resolve, reject) => {
      const poll = setInterval(async () => {
        try {
          const res = await api.get(`/check-links/status/${jobId}`);
          if (res.data.status === 'completed') {
            clearInterval(poll);
            setResults(res.data.result.brokenLinks);
            resolve(res.data.result.brokenLinks);
          } else if (res.data.status === 'error') {
            clearInterval(poll);
            toastError('Something went wrong while checking your links.');
            reject(new Error('Job failed.'));
          }
        } catch (err) {
          clearInterval(poll);
          reject(err);
        }
      }, 3000);
    });
  } catch (err) {
    toastError('Unable to start the link check.');
    throw err;
  }
};

export const createCustomer = async (email) => api.post('/create-customer', { email });
export const createCheckoutSession = async (customerId, plan) =>
  api.post('/create-checkout-session', { customerId, plan });
