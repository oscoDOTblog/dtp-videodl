'use client';

import { useState, useEffect, cloneElement } from 'react';
import LoginPage from './LoginPage';

const AUTH_KEY = 'videodl-auth';

export default function AuthWrapper({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [authRequired, setAuthRequired] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const checkAuth = async () => {
      try {
        const response = await fetch('/api/auth');
        if (cancelled) return;

        if (response.ok) {
          const data = await response.json();
          setAuthRequired(Boolean(data.required));

          if (!data.required) {
            setIsAuthenticated(true);
            return;
          }

          const authToken = localStorage.getItem(AUTH_KEY);
          if (authToken === 'true') {
            setIsAuthenticated(true);
          }
        } else {
          setAuthRequired(false);
          setIsAuthenticated(true);
        }
      } catch {
        if (!cancelled) {
          setAuthRequired(false);
          setIsAuthenticated(true);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    checkAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleAuthenticated = () => {
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    localStorage.removeItem(AUTH_KEY);
    setIsAuthenticated(false);
  };

  if (isLoading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'linear-gradient(135deg, #141414 0%, #1a1a1a 100%)',
          color: '#fff',
        }}
      >
        Loading...
      </div>
    );
  }

  if (authRequired && !isAuthenticated) {
    return <LoginPage onAuthenticated={handleAuthenticated} />;
  }

  return cloneElement(children, { onLogout: authRequired ? handleLogout : undefined });
}
