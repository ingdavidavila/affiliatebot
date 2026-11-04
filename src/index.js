import { createRoot } from 'react-dom/client';
import { GoogleOAuthProvider } from '@react-oauth/google';
import App from './App';
import './App.css';

const clientId = process.env.REACT_APP_GOOGLE_CLIENT_ID;
console.log('Client ID loaded:', clientId); // Debug log

if (!clientId) {
  console.error('REACT_APP_GOOGLE_CLIENT_ID is missing from .env file!');
}

const root = createRoot(document.getElementById('root'));
root.render(
  <GoogleOAuthProvider clientId={clientId}>
    <App />
  </GoogleOAuthProvider>
);