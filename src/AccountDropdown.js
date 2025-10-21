import React, { useState } from "react";
import { toast } from "react-toastify";
import { cancelSubscription } from "./api";

function AccountDropdown({ user, onLogout }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleCancel = async () => {
    const confirmCancel = window.confirm(
      "Are you sure you want to cancel your subscription? Your plan will remain active until the current billing period ends. No refund will be issued."
    );
    if (!confirmCancel) return;

    setLoading(true);
    try {
      const token = localStorage.getItem("authToken");
      await cancelSubscription(token);
      toast.success("Subscription canceled successfully.");
    } catch (err) {
      console.error(err);
      toast.error("Failed to cancel subscription.");
    } finally {
      setLoading(false);
      setOpen(false);
    }
  };

  return (
    <div className="dropdown">
      <button
        className="btn btn-outline-secondary dropdown-toggle"
        type="button"
        id="accountDropdown"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        Account
      </button>

    <ul className={`dropdown-menu ${open ? "show" : ""}`} aria-labelledby="accountDropdown" style={{ position: "absolute", zIndex: 9999 }}>
  <li className="dropdown-item-text">
    <strong>{user?.email}</strong>
  </li>
  <li className="dropdown-item-text text-muted">
    {user.subscription_end ? (
      <small>
        Active until{" "}
        {new Date(user.subscription_end).toLocaleDateString(undefined, {
          year: "numeric",
          month: "short",
          day: "numeric",
        })}
      </small>
    ) : (
      <small>Subscription active</small>
    )}
  </li>
  <li>
    <button className="dropdown-item text-danger" onClick={handleCancel} disabled={loading}>
      {loading ? "Processing..." : "Cancel Subscription"}
    </button>
  </li>
  <li>
    <hr className="dropdown-divider" />
  </li>
  <li>
    <button className="dropdown-item" onClick={onLogout}>Log Out</button>
  </li>
    </ul>
    </div>
  );
}

export default AccountDropdown;
