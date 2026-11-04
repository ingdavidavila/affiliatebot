import React, { useState, useEffect } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import { Elements, PaymentElement, useElements, useStripe } from '@stripe/react-stripe-js';
import { createCheckoutSession } from './api';
import { toast } from 'react-toastify';

const stripePromise = loadStripe(process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY);

const CheckoutForm = ({ customerId, plan, clientSecret, onSuccess, onClose }) => {
  const stripe = useStripe();
  const elements = useElements();
  const [message, setMessage] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!stripe || !elements || !clientSecret) {
      setMessage('Payment not initialized. Please try again.');
      return;
    }

    setIsLoading(true);

    const { error } = await stripe.confirmPayment({
      elements,
      confirmParams: {
        return_url: 'https://www.affiliatesbot.com/success',
      },
    });

    if (error) {
      setMessage(error.message);
      toast.error(error.message);
    } else {
      setMessage('Payment succeeded!');
      toast.success('Payment succeeded!');
      if (onSuccess) onSuccess();
    }

    setIsLoading(false);
  };

  if (!clientSecret) return <div>{message || 'Loading payment form...'}</div>;

  return (
    <form onSubmit={handleSubmit} className="payment-form">
      <PaymentElement />
      <button
        type="submit"
        disabled={isLoading || !stripe || !elements}
        className="btn btn-success stylish-btn"
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
        {isLoading ? 'Processing...' : `Pay $${plan === 'monthly' ? '15' : '100'}`}
      </button>
      {message && <div className="error">{message}</div>}
      <button
        type="button"
        onClick={onClose}
        className="btn btn-secondary mt-2"
        style={{ marginLeft: '10px' }}
      >
        Cancel
      </button>
    </form>
  );
};

const PaymentModal = ({ user, plan, onSuccess, onClose }) => {
  const [clientSecret, setClientSecret] = useState(null);

  useEffect(() => {
    const fetchClientSecret = async () => {
      try {
        const response = await createCheckoutSession(user.stripe_customer_id, plan);
        console.log('API Response:', response);
        if (response && response.clientSecret) {
          setClientSecret(response.clientSecret);
        } else {
          throw new Error('Invalid or missing clientSecret in response');
        }
      } catch (err) {
        console.error('Error fetching client secret:', err);
        toast.error(`Payment initialization failed: ${err.message}`);
      }
    };
    fetchClientSecret();
  }, [user.stripe_customer_id, plan]);

  return clientSecret ? (
    <Elements stripe={stripePromise} options={{ clientSecret }}>
      <CheckoutForm
        customerId={user.stripe_customer_id}
        plan={plan}
        clientSecret={clientSecret}
        onSuccess={onSuccess}
        onClose={onClose}
      />
    </Elements>
  ) : (
    <div>Loading payment form...</div>
  );
};

export default PaymentModal;