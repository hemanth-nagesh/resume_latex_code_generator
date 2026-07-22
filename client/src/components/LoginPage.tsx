import { useState, useEffect, useCallback } from 'react';
import { verifyPasscode } from '../services/auth';

const PIN_LENGTH = 4;

interface Props {
  onUnlock: () => void;
}

export default function LoginPage({ onUnlock }: Props) {
  const [pin, setPin] = useState<string[]>([]);
  const [shake, setShake] = useState(false);
  const [unlocking, setUnlocking] = useState(false);
  const [error, setError] = useState(false);

  const addDigit = useCallback((d: string) => {
    if (unlocking) return;
    setError(false);
    setPin((prev) => {
      if (prev.length >= PIN_LENGTH) return prev;
      const next = [...prev, d];
      return next;
    });
  }, [unlocking]);

  const removeDigit = useCallback(() => {
    if (unlocking) return;
    setError(false);
    setPin((prev) => prev.slice(0, -1));
  }, [unlocking]);

  // Auto-submit when PIN is full
  useEffect(() => {
    if (pin.length !== PIN_LENGTH) return;
    const code = pin.join('');
    setUnlocking(true);

    verifyPasscode(code)
      .then((ok) => {
        if (ok) {
          onUnlock();
        } else {
          setUnlocking(false);
          setError(true);
          setShake(true);
          setTimeout(() => setShake(false), 500);
          setPin([]);
        }
      })
      .catch(() => {
        setUnlocking(false);
        setError(true);
        setShake(true);
        setTimeout(() => setShake(false), 500);
        setPin([]);
      });
  }, [pin, onUnlock]);

  // Keyboard support
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key >= '0' && e.key <= '9') addDigit(e.key);
      else if (e.key === 'Backspace') removeDigit();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [addDigit, removeDigit]);

  const keys = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
  ];

  return (
    <div className="login-wrapper">
      <div className={`login-card ${shake ? 'login-shake' : ''}`}>
        {/* Header */}
        <div className="login-header">
          <div className="login-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          </div>
          <h2>{unlocking ? 'Verifying...' : 'Enter Passcode'}</h2>
          {error && <p className="login-error">Wrong passcode — try again</p>}
          {!error && <p className="login-subtitle">Secure access to Resume AI Builder</p>}
        </div>

        {/* PIN dots */}
        <div className="pin-dots">
          {Array.from({ length: PIN_LENGTH }, (_, i) => (
            <div
              key={i}
              className={`pin-dot ${i < pin.length ? 'filled' : ''} ${unlocking ? 'loading' : ''}`}
            >
              {unlocking && i < pin.length && (
                <div className="pin-dot-spinner" />
              )}
            </div>
          ))}
        </div>

        {/* Keypad */}
        <div className="keypad">
          {keys.map((row, ri) => (
            <div key={ri} className="keypad-row">
              {row.map((d) => (
                <button
                  key={d}
                  className="keypad-key"
                  onClick={() => addDigit(d)}
                  disabled={unlocking}
                >
                  <span className="key-digit">{d}</span>
                </button>
              ))}
            </div>
          ))}
          <div className="keypad-row">
            <div className="keypad-key keypad-empty" />
            <button
              className="keypad-key"
              onClick={() => addDigit('0')}
              disabled={unlocking}
            >
              <span className="key-digit">0</span>
            </button>
            <button
              className="keypad-key keypad-delete"
              onClick={removeDigit}
              disabled={unlocking || pin.length === 0}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 4H8l-7 8 7 8h13a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z" />
                <line x1="18" y1="9" x2="12" y2="15" />
                <line x1="12" y1="9" x2="18" y2="15" />
              </svg>
            </button>
          </div>
        </div>

        <p className="login-hint">or type on your keyboard</p>
      </div>
    </div>
  );
}
