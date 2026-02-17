import React, { useState, useRef, useEffect } from 'react';
import './VoiceRecorder.css';

const VoiceRecorder = ({ onRecordingComplete, onRecordingStateChange, disabled }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [permissionError, setPermissionError] = useState(null);
  
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);

  useEffect(() => {
    // Cleanup on unmount
    return () => {
      stopRecording();
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  const startRecording = async () => {
    try {
      setPermissionError(null);
      
      // Request microphone permission
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 44100
        } 
      });

      // Create MediaRecorder
      const mimeType = MediaRecorder.isTypeSupported('audio/webm') 
        ? 'audio/webm' 
        : 'audio/mp4';
      
      mediaRecorderRef.current = new MediaRecorder(stream, {
        mimeType: mimeType
      });

      chunksRef.current = [];

      // Collect audio data
      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      // Handle recording stop
      mediaRecorderRef.current.onstop = () => {
        const audioBlob = new Blob(chunksRef.current, { type: mimeType });
        onRecordingComplete(audioBlob);
        
        // Stop all tracks
        stream.getTracks().forEach(track => track.stop());
        
        // Reset timer
        setRecordingTime(0);
        if (timerRef.current) {
          clearInterval(timerRef.current);
        }
      };

      // Start recording
      mediaRecorderRef.current.start();
      setIsRecording(true);
      onRecordingStateChange(true);

      // Start timer
      timerRef.current = setInterval(() => {
        setRecordingTime(prev => prev + 1);
      }, 1000);

      // Auto-stop after 60 seconds
      setTimeout(() => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
          stopRecording();
        }
      }, 60000);

    } catch (error) {
      console.error('Error accessing microphone:', error);
      
      if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
        setPermissionError('يرجى السماح بالوصول إلى الميكروفون');
      } else if (error.name === 'NotFoundError') {
        setPermissionError('لم يتم العثور على ميكروفون');
      } else {
        setPermissionError('حدث خطأ في الوصول إلى الميكروفون');
      }
      
      setIsRecording(false);
      onRecordingStateChange(false);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      onRecordingStateChange(false);
    }
  };

  const cancelRecording = () => {
    if (mediaRecorderRef.current) {
      // Stop without triggering ondataavailable
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      mediaRecorderRef.current = null;
      chunksRef.current = [];
      setIsRecording(false);
      onRecordingStateChange(false);
      setRecordingTime(0);
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    }
  };

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="voice-recorder">
      {/* Recording Button */}
      <button
        type="button"
        className={`voice-button ${isRecording ? 'recording' : ''}`}
        onClick={toggleRecording}
        disabled={disabled}
        title={isRecording ? 'إيقاف التسجيل' : 'بدء التسجيل الصوتي'}
      >
        {isRecording ? (
          <>
            {/* Stop Icon */}
            <svg 
              width="20" 
              height="20" 
              viewBox="0 0 24 24" 
              fill="currentColor"
            >
              <rect x="6" y="6" width="12" height="12" rx="2"/>
            </svg>
            <span className="recording-pulse"></span>
          </>
        ) : (
          /* Microphone Icon */
          <svg 
            width="20" 
            height="20" 
            viewBox="0 0 24 24" 
            fill="none" 
            stroke="currentColor" 
            strokeWidth="2"
            strokeLinecap="round" 
            strokeLinejoin="round"
          >
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
        )}
      </button>

      {/* Recording Indicator */}
      {isRecording && (
        <div className="recording-indicator">
          <span className="recording-dot"></span>
          <span className="recording-time">{formatTime(recordingTime)}</span>
          <button
            type="button"
            className="cancel-recording-btn"
            onClick={cancelRecording}
            title="إلغاء التسجيل"
          >
            ✕
          </button>
        </div>
      )}

      {/* Permission Error */}
      {permissionError && (
        <div className="permission-error">
          ⚠️ {permissionError}
        </div>
      )}
    </div>
  );
};

export default VoiceRecorder;
