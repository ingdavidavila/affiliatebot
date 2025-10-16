import React, { useState, useEffect } from 'react';
import { GoogleLogin } from '@react-oauth/google';
import axios from 'axios';
import { loadStripe } from '@stripe/stripe-js';
import { Elements } from '@stripe/react-stripe-js';
import './App.css';

const stripePromise = loadStripe(process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY);

function App() {
  const [user, setUser] = useState(null);
  const [error, setError] = useState('');
  const [results, setResults] = useState([]);
  const [showLogin, setShowLogin] = useState(false);
  const [loading, setLoading] = useState(false);
  const [paid, setPaid] = useState(false);

  useEffect(() => {
    console.log('App component mounted');
    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get('session_id');
    if (sessionId) {
      verifyPayment(sessionId);
    }
  }, []);

  const verifyPayment = async (sessionId) => {
    setLoading(true);
    try {
      const response = await axios.post('http://localhost:3001/api/verify-payment', { sessionId });
      setPaid(response.data.paid);
      if (response.data.paid && user) {
        const channelId = prompt('Re-enter your YouTube Channel ID for full check:') || user.lastChannelId;
        if (channelId) {
          await checkLinks(channelId, true); // Re-run with all videos
        }
      }
    } catch (err) {
      setError('Payment verification failed: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLoginSuccess = async (credentialResponse) => {
    console.log('Login Success - Credential Response:', credentialResponse);
    setLoading(true);
    try {
      const authResponse = await axios.post('http://localhost:3001/api/auth/google', {
        token: credentialResponse.credential,
      });
      console.log('Auth Response from Backend:', authResponse.data);
      const userData = authResponse.data.user;
      setUser({ ...userData, lastChannelId: null }); // Store last used channelId

      const statusResponse = await axios.get(`http://localhost:3001/api/user-status?email=${userData.email}`);
      setPaid(statusResponse.data.paid);

      setError('');
      setShowLogin(false);

      const channelId = prompt('Please enter your YouTube Channel ID (e.g., UC1234567890):');
      if (channelId) {
        setUser(prev => ({ ...prev, lastChannelId: channelId }));
        await checkLinks(channelId, statusResponse.data.paid);
      } else {
        setError('Channel ID is required to check links.');
      }
    } catch (err) {
      console.error('Auth Error Details:', {
        message: err.message,
        response: err.response?.data,
        status: err.response?.status,
      });
      setError(err.response?.data?.error || 'Failed to log in with Google');
    } finally {
      setLoading(false);
    }
  };

  const handleLoginFailure = () => {
    console.log('Login Failed');
    setError('Failed to log in with Google');
    setShowLogin(false);
    setLoading(false);
  };

  const checkLinks = async (channelId, isPaid) => {
    setLoading(true);
    try {
      const maxVideos = isPaid ? -1 : 50; // -1 signals backend to use total video count
      const checkResponse = await axios.post('http://localhost:3001/api/check-links', {
        channelId,
        maxVideos,
      });
      setResults(checkResponse.data.brokenLinks || []);
      setError('');
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to check links');
    } finally {
      setLoading(false);
    }
  };

  const handlePayment = async (plan) => {
    setLoading(true);
    try {
      const { data: { customerId } } = await axios.post('http://localhost:3001/api/create-customer', { email: user.email });
      const { data: { sessionId } } = await axios.post('http://localhost:3001/api/create-checkout-session', { customerId, plan });
      const stripe = await stripePromise;
      await stripe.redirectToCheckout({ sessionId });
    } catch (err) {
      setError('Payment initiation failed: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-wrapper">
    <div className="container">
      <div className="card">
        <div className="logo-placeholder">
          <div className="logo">AffiliateBot</div>
        </div>
        <h1 className="heading">Welcome to AffiliateBot</h1>
        <p className="instructions">
          Click the button below to log in with your YouTube account and check for broken affiliate links in your videos.
        </p>
        {!user ? (
          <div>
            <button
              className="btn btn-primary"
              onClick={() => setShowLogin(true)}
              disabled={loading}
            >
              {loading ? 'Logging in...' : 'Log in with YouTube'}
            </button>
            {showLogin && (
              <div className="mt-3">
                <GoogleLogin
                  onSuccess={handleLoginSuccess}
                  onError={handleLoginFailure}
                  scope="https://www.googleapis.com/auth/youtube.readonly"
                  text="signin_with"
                  shape="rectangular"
                  theme="filled_blue"
                />
              </div>
            )}
          </div>
        ) : (
          <div>
            <p className="logged-in">Logged in as {user.email}</p>
            <button
              className="logout-btn"
              onClick={() => {
                setUser(null);
                setResults([]);
                setError('');
                setPaid(false);
              }}
            >
              Log Out
            </button>
          </div>
        )}
        {loading && <p className="loading">Checking links...</p>}
        {error && <p className="error">{error}</p>}
        {results.length === 0 && !error && user && <p className="no-results">No broken links found.</p>}
        {results.length > 0 && !paid && (
          <div className="paywall">
            <p>{results.length} broken links found. Please subscribe to view details:</p>
            <button
              className="btn btn-success stylish-btn me-2"
              onClick={() => handlePayment('monthly')}
              style={{ padding: '10px 20px', background: 'linear-gradient(45deg, #28a745, #218838)', border: 'none', boxShadow: '0 4px 8px rgba(0,0,0,0.2)', transition: 'all 0.3s' }}
              onMouseOver={(e) => (e.target.style.transform = 'scale(1.05)')}
              onMouseOut={(e) => (e.target.style.transform = 'scale(1)')}
            >
              $15/month
            </button>
            <button
              className="btn btn-success stylish-btn"
              onClick={() => handlePayment('yearly')}
              style={{ padding: '10px 20px', background: 'linear-gradient(45deg, #28a745, #218838)', border: 'none', boxShadow: '0 4px 8px rgba(0,0,0,0.2)', transition: 'all 0.3s' }}
              onMouseOver={(e) => (e.target.style.transform = 'scale(1.05)')}
              onMouseOut={(e) => (e.target.style.transform = 'scale(1)')}
            >
              $100/year
            </button>
            <p className="promise">Coming soon: Automated daily checks will be emailed to you!</p>
          </div>
        )}
        {results.length > 0 && paid && (
          <div className="results-table">
            <table className="table">
              <thead>
                <tr>
                  <th>Video URL</th>
                  <th>Broken Link</th>
                </tr>
              </thead>
              <tbody>
                {results.map((result, index) => (
                  <tr key={index}>
                    <td>
                      <a
                        href={`https://www.youtube.com/watch?v=${result.videoId}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="table-link"
                      >
                        Watch Video
                      </a>
                    </td>
                    <td>
                      <a
                        href={result.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="table-link"
                        style={{ wordBreak: 'break-all' }}
                      >
                        {result.link}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
        <footer className="footer bg-dark text-white text-center py-3">
          <p className="mb-0">This website was made by <a href="https://workingrobotsinc.com" target="_blank" rel="noopener noreferrer" className="text-info">WorkingRobots Inc.</a></p>
        </footer>
    </div>
    </div>
  );
}

export default App;