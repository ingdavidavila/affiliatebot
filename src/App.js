import React, { useState, useEffect } from 'react';
import { GoogleLogin } from '@react-oauth/google';
import axios from 'axios';
import './App.css';

function App() {
  const [user, setUser] = useState(null);
  const [error, setError] = useState('');
  const [results, setResults] = useState([]);
  const [showLogin, setShowLogin] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    console.log('App component mounted');
  }, []);

 const handleLoginSuccess = async (credentialResponse) => {
  console.log('Login Success - Credential Response:', credentialResponse);
  setLoading(true);
  try {
    const authResponse = await axios.post('http://localhost:3001/api/auth/google', {
      token: credentialResponse.credential,
    });
    console.log('Auth Response from Backend:', authResponse.data);
    setUser(authResponse.data.user);
    setError('');
    setShowLogin(false);

    // Temporary: Use a placeholder or prompt for channelId
    const channelId = prompt('Please enter your YouTube Channel ID (e.g., UC1234567890):');
    if (channelId) {
      await checkLinks(channelId);
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

  const checkLinks = async (channelId) => {
    setLoading(true);
    try {
      const checkResponse = await axios.post('http://localhost:3001/api/check-links', {
        channelId,
        maxVideos: 50,
      });
      setResults(checkResponse.data.brokenLinks || []);
      setError('');
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to check links');
    } finally {
      setLoading(false);
    }
  };

  return (
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
              }}
            >
              Log Out
            </button>
          </div>
        )}
        {loading && <p className="loading">Checking links...</p>}
        {error && <p className="error">{error}</p>}
        {results.length > 0 ? (
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
                        className="table a"
                      >
                        Watch Video
                      </a>
                    </td>
                    <td>
                      <a
                        href={result.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="table a"
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
        ) : (
          !error && user && <p className="no-results">No broken links found.</p>
        )}
      </div>
    </div>
  );
}

export default App;