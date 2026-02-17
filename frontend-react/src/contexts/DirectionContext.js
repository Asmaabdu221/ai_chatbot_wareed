import React, { createContext, useContext, useLayoutEffect, useMemo, useState } from 'react';

const DirectionContext = createContext({
  direction: 'rtl',
  setDirection: () => {},
});

const STORAGE_KEY = 'wareed_direction';

const readStoredDirection = () => {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'ltr' || stored === 'rtl' ? stored : null;
};

export const DirectionProvider = ({ children, defaultDirection = 'rtl' }) => {
  const [direction, setDirectionState] = useState(() => {
    return readStoredDirection() || (defaultDirection === 'ltr' ? 'ltr' : 'rtl');
  });

  const setDirection = (nextDirection) => {
    const value = nextDirection === 'ltr' ? 'ltr' : 'rtl';
    setDirectionState(value);
    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, value);
    }
  };

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.setAttribute('dir', direction);
    const appRoot = document.getElementById('root');
    if (appRoot) {
      appRoot.setAttribute('dir', direction);
    }
  }, [direction]);

  const value = useMemo(() => ({ direction, setDirection }), [direction]);

  return <DirectionContext.Provider value={value}>{children}</DirectionContext.Provider>;
};

export const useDirection = () => useContext(DirectionContext);
