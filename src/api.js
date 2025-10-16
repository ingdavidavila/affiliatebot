import axios from 'axios';

export const verifyPayment = async (sessionId, setLoading, setPaid, setShowChannelPrompt, setChannelInput, user, toastError) => {
  setLoading(true);
  try {
    const response = await axios.post('http://localhost:3001/api/verify-payment', { sessionId });
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
    const response = await axios.post('http://localhost:3001/api/auth/google', { token });
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
    const response = await axios.get(`http://localhost:3001/api/user-status?email=${email}`);
    if (!response.data.paid && response.data.paid !== false) {
      console.warn('Unexpected user status response structure:', response.data);
      response.data.paid = false; // Default to false if undefined
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
    const response = await axios.post('http://localhost:3001/api/check-links', { channelId, maxVideos });
    const brokenLinks = response.data.brokenLinks || [];
    setResults(brokenLinks); // Directly set the results array
    return response; // Keep return for potential future use
  } catch (err) {
    toastError('Something went wrong while checking your links. Please try again.');
    throw err;
  }
};

export const createCustomer = async (email) => {
  return await axios.post('http://localhost:3001/api/create-customer', { email });
};

export const createCheckoutSession = async (customerId, plan) => {
  return await axios.post('http://localhost:3001/api/create-checkout-session', { customerId, plan });
};