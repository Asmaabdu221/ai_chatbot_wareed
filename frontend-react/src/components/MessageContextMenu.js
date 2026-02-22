import React, { useEffect, useRef } from 'react';
import './MessageContextMenu.css';

/**
 * Modern WhatsApp-style context menu for messages.
 */
const MessageContextMenu = ({
    x,
    y,
    onClose,
    onAction,
    isMobile = false
}) => {
    const menuRef = useRef(null);

    useEffect(() => {
        const handleClickOutside = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) {
                onClose();
            }
        };
        const handleEscape = (e) => {
            if (e.key === 'Escape') onClose();
        };

        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('keydown', handleEscape);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('keydown', handleEscape);
        };
    }, [onClose]);

    const menuOptions = [
        { id: 'copy', label: 'نسخ' },
        { id: 'delete', label: 'حذف' },
        { id: 'share', label: 'مشاركة' },
        { id: 'reply', label: 'رد' },
        { id: 'pin', label: 'تثبيت' },
    ];

    const style = isMobile ? {} : { top: `${y}px`, left: `${x}px` };

    return (
        <div
            className={`message-context-menu-backdrop ${isMobile ? 'mobile' : ''}`}
            onClick={(e) => {
                if (e.target === e.currentTarget) onClose();
            }}
        >
            <div
                ref={menuRef}
                className={`message-context-menu ${isMobile ? 'bottom-sheet' : 'popup'}`}
                style={style}
                role="menu"
            >
                {isMobile && <div className="bottom-sheet-drag-handle" />}
                <ul className="message-menu-list">
                    {menuOptions.map((opt) => (
                        <li
                            key={opt.id}
                            className="message-menu-item"
                            onClick={() => {
                                onAction(opt.id);
                                onClose();
                            }}
                            role="menuitem"
                        >
                            <span className="menu-item-label">{opt.label}</span>
                        </li>
                    ))}
                </ul>
            </div>
        </div>
    );
};

export default MessageContextMenu;
