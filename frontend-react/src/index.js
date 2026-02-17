import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import { DirectionProvider } from './contexts/DirectionContext';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <DirectionProvider defaultDirection="rtl">
      <App />
    </DirectionProvider>
  </React.StrictMode>
);
