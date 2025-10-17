import axios from 'axios';

// Automatically use the correct backend URL
const API_BASE_URL =
  process.env.NODE_ENV === 'production'
    ? 'https://www.affiliatesbot.com/api'
    : 'http://localhost:3001/api';

// Create a preconfigured Axios instance
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 35000, // 35 seconds, slightly above Heroku's 30s H12 limit
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
    const response = await api.post('/verify-payment', { sessionId });
    setPaid(response.data.paid);
    if (response.data.paid && user) {
      setShowChannelPrompt(true);
      setChannelInput(user.lastChannelId || '');
    }
  } catch (err) {
    toastError('Something went wrong while verifying your payment. Please try again later.');
  } finally {
    setLoading(false);
  }
};

export const authGoogle = async (token) => {
  try {
    const response = await api.post('/auth/google', { token });
    if (!response.data.user && !response.data) {
      console.warn('Unexpected auth response structure:', response.data);
      throw new Error('Invalid authentication response from backend');
    }
    return response;
  } catch (err) {
    console.error('AuthGoogle Error:', {
      message: err.message,
      response: err.response?.data,
      status: err.response?.status,
      fullError: err,
    });
    throw err;
  }
};

export const getUserStatus = async (email) => {
  try {
    const response = await api.get(`/user-status?email=${email}`);
    if (!response.data.paid && response.data.paid !== false) {
      console.warn('Unexpected user status response structure:', response.data);
      response.data.paid = false;
    }
    return response;
  } catch (err) {
    console.error('GetUserStatus Error:', {
      message: err.message,
      response: err.response?.data,
      status: err.response?.status,
      fullError: err,
    });
    throw err;
  }
};

export const checkLinks = async (channelId, maxVideos, setResults, toastError) => {
  try {
    // Step 1: Start job
    const { data } = await axios.post(`${process.env.REACT_APP_API_URL}/api/check-links`, {
      channelId,
      maxVideos,
    });
    const jobId = data.jobId;

    // Step 2: Poll for results
    const poll = setInterval(async () => {
      const res = await axios.get(`${process.env.REACT_APP_API_URL}/api/check-links/status/${jobId}`);
      if (res.data.status === 'completed') {
        clearInterval(poll);
        setResults(res.data.result.brokenLinks);
      } else if (res.data.status === 'error') {
        clearInterval(poll);
        toastError('Something went wrong while checking your links.');
      }
    }, 3000);
  } catch (err) {
    toastError('Unable to start the link check.');
  }
};

export const createCustomer = async (email) => {
  return await api.post('/create-customer', { email });
};

export const createCheckoutSession = async (customerId, plan) => {
  return await api.post('/create-checkout-session', { customerId, plan });
};
