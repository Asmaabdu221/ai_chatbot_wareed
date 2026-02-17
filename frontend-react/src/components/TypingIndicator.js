import React from 'react';
import './TypingIndicator.css';

const TypingIndicator = () => {
  return (
    <div className="message-wrapper assistant">
      <div className="message-container">
        <div className="message-avatar">🤖</div>
        <div className="typing-indicator">
          <span></span>
          <span></span>
          <span></span>
          <span className="typing-text">جاري التفكير...</span>
        </div>
      </div>
    </div>
  );
};

export default TypingIndicator;
