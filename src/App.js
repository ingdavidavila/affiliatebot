import React, { useState, useEffect } from 'react';
import { GoogleLogin } from '@react-oauth/google';
import { loadStripe } from '@stripe/stripe-js';
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import './App.css';
import {
  verifyPayment,
  authGoogle,
  getUserStatus,
  checkLinks as apiCheckLinks,
  createCustomer,
  createCheckoutSession,
} from './api';
import PaymentModal from './PaymentForm'; // New component

const stripePromise = loadStripe(process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY);

function App() {
  const [user, setUser] = useState(null);
  const [error, setError] = useState('');
  const [results, setResults] = useState([]);
  const [showLogin, setShowLogin] = useState(false);
  const [loading, setLoading] = useState(false);
  const [paid, setPaid] = useState(false);
  const [showChannelPrompt, setShowChannelPrompt] = useState(false);
  const [channelInput, setChannelInput] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [showPaymentModal, setShowPaymentModal] = useState(false); // New state for modal
  const [selectedPlan, setSelectedPlan] = useState(null); // Track selected plan
  const itemsPerPage = 10;

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get('session_id');
    if (sessionId) {
      verifyPayment(
        sessionId,
        setLoading,
        setPaid,
        setShowChannelPrompt,
        setChannelInput,
        user,
        (msg) => toast.error(msg)
      );
    }
  }, [user]);

  const handleLoginSuccess = async (credentialResponse) => {
    setLoading(true);
    try {
      const authResponse = await authGoogle(credentialResponse.credential);
      const userData = authResponse.data.user || authResponse.data;
      setUser({ ...userData, lastChannelId: null });

      const statusResponse = await getUserStatus(userData.email);
      setPaid(statusResponse.data.paid || false);

      setError('');
      setShowLogin(false);
      setShowChannelPrompt(true);
      setChannelInput('');
      toast.success('Logged in successfully!');
    } catch (err) {
      console.error('Auth error details:', {
        message: err.message,
        response: err.response?.data,
        status: err.response?.status,
      });
      const message = err.response?.data?.error || 'Failed to log in with Google.';
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const handleLoginFailure = () => {
    setError('Failed to log in with Google.');
    toast.error('Failed to log in with Google.');
    setShowLogin(false);
    setLoading(false);
  };

  const handleChannelSubmit = async () => {
    if (!channelInput.trim()) {
      setError('Channel ID is required to check links.');
      toast.error('Channel ID is required.');
      return;
    }
    setLoading(true);
    const maxRetries = 3;
    const retryDelay = 5000;
    let attempt = 0;

    try {
      setUser((prev) => ({ ...prev, lastChannelId: channelInput }));
      const maxVideos = paid ? -1 : 50;
      let results;
      while (attempt < maxRetries) {
        try {
          results = await apiCheckLinks(channelInput, maxVideos, setResults, (msg) => toast.error(msg));
          setResults(results);
          setShowChannelPrompt(false);
          setCurrentPage(1);
          toast.success('Check complete!');
          break;
        } catch (err) {
          attempt++;
          if (err.code === 'ECONNABORTED' || err.response?.status === 503) {
            if (attempt === maxRetries) {
              throw new Error('Check timed out after retries.');
            }
            console.log(`Attempt ${attempt} failed with timeout, retrying in ${retryDelay}ms...`);
            await new Promise(resolve => setTimeout(resolve, retryDelay));
          } else {
            throw err;
          }
        }
      }
      if (!results) {
        throw new Error('No results received after retries.');
      }
    } catch (err) {
      const message = err.message || 'Failed to check links.';
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const handlePayment = (plan) => {
    setSelectedPlan(plan);
    setShowPaymentModal(true);
  };

  const handlePaymentSuccess = () => {
    setShowPaymentModal(false);
    setPaid(true); // Update paid status after success
    setSelectedPlan(null);
    toast.success('Payment successful! Checking unlimited links is now enabled.');
  };

  const handlePaymentClose = () => {
    setShowPaymentModal(false);
    setSelectedPlan(null);
  };

  const indexOfLastItem = currentPage * itemsPerPage;
  const indexOfFirstItem = indexOfLastItem - itemsPerPage;
  const currentResults = results.slice(indexOfFirstItem, indexOfLastItem);
  const totalPages = Math.ceil(results.length / itemsPerPage);

  const paginate = (pageNumber) => setCurrentPage(pageNumber);

  return (
    <div className="app-wrapper">
      <ToastContainer position="top-right" autoClose={4000} />
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
                  toast.info('Logged out.');
                }}
              >
                Log Out
              </button>
            </div>
          )}

          {loading && <p className="loading">Checking links...</p>}
          {error && <p className="error">{error}</p>}
          {results.length === 0 && !error && user && !loading && (
            <p className="no-results">No broken links found.</p>
          )}

          {showChannelPrompt && (
            <div className="channel-prompt">
              <h2 className="heading">Enter Your Channel ID</h2>
              <input
                type="text"
                className="channel-input"
                value={channelInput}
                onChange={(e) => setChannelInput(e.target.value)}
                placeholder="e.g., UC1234567890"
              />
              <p className="channel-help">
                Don’t know your Channel ID?{' '}
                <a
                  href="https://support.google.com/youtube/answer/3250431"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Find it here
                </a>.
              </p>
              <button
                className="btn btn-primary mt-3"
                onClick={handleChannelSubmit}
                disabled={loading}
              >
                {loading ? 'Checking...' : 'Submit'}
              </button>
            </div>
          )}

          {results.length > 0 && !paid && (
            <div className="paywall">
              <p>{results.length} broken links found. Please subscribe to view details:</p>
              <button
                className="btn btn-success stylish-btn me-2"
                onClick={() => handlePayment('monthly')}
                style={{
                  padding: '10px 20px',
                  background: 'linear-gradient(45deg, #28a745, #218838)',
                  border: 'none',
                  boxShadow: '0 4px 8px rgba(0,0,0,0.2)',
                  transition: 'all 0.3s',
                }}
                onMouseOver={(e) => (e.target.style.transform = 'scale(1.05)')}
                onMouseOut={(e) => (e.target.style.transform = 'scale(1)')}
              >
                $15/month
              </button>
              <button
                className="btn btn-success stylish-btn"
                onClick={() => handlePayment('yearly')}
                style={{
                  padding: '10px 20px',
                  background: 'linear-gradient(45deg, #28a745, #218838)',
                  border: 'none',
                  boxShadow: '0 4px 8px rgba(0,0,0,0.2)',
                  transition: 'all 0.3s',
                }}
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
                  {currentResults.map((result, index) => (
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
              <div className="pagination" style={{ marginTop: '1rem', textAlign: 'center' }}>
                <button
                  className="btn btn-secondary"
                  onClick={() => paginate(currentPage - 1)}
                  disabled={currentPage === 1}
                  style={{ marginRight: '0.5rem' }}
                >
                  Previous
                </button>
                <span>
                  Page {currentPage} of {totalPages}
                </span>
                <button
                  className="btn btn-secondary"
                  onClick={() => paginate(currentPage + 1)}
                  disabled={currentPage === totalPages}
                  style={{ marginLeft: '0.5rem' }}
                >
                  Next
                </button>
              </div>
            </div>
          )}

          {showPaymentModal && user && (
            <div className="modal" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 }}>
              <div style={{ backgroundColor: 'white', padding: '20px', borderRadius: '5px', maxWidth: '500px', width: '100%' }}>
                <PaymentModal
                  user={user}
                  plan={selectedPlan}
                  onSuccess={handlePaymentSuccess}
                  onClose={handlePaymentClose}
                />
              </div>
            </div>
          )}
        </div>

        <footer className="footer bg-dark text-white text-center py-3">
          <p className="mb-0">
            This website was made by{' '}
            <a
              href="https://workingrobotsinc.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-info"
            >
              WorkingRobots Inc.
            </a>
          </p>
        </footer>
      </div>
    </div>
  );
}

export default App;