import React, { useCallback, useEffect, useRef, useState } from 'react';
import styles from './PixelAvatar.module.css';

interface PixelAvatarProps {
    isStreaming?: boolean;
    isUserTyping?: boolean;
}

const PixelAvatar: React.FC<PixelAvatarProps> = ({
    isStreaming = false,
    isUserTyping = false,
}) => {
    const [isDizzy, setIsDizzy] = useState(false);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        return () => {
            if (timerRef.current) clearTimeout(timerRef.current);
        };
    }, []);

    const handleClick = useCallback(() => {
        if (isDizzy) return;
        setIsDizzy(true);
        timerRef.current = setTimeout(() => {
            setIsDizzy(false);
            timerRef.current = null;
        }, 600);
    }, [isDizzy]);

    // Determine current active animation state class
    let botStateClass = styles.idle;
    if (isDizzy) {
        botStateClass = styles.dizzy;
    } else if (isStreaming) {
        botStateClass = styles.thinking;
    } else if (isUserTyping) {
        botStateClass = styles.typing;
    }

    return (
        <div 
            className={`${styles['pixel-avatar-container']} ${botStateClass}`} 
            onClick={handleClick}
        >
            <svg 
                className={styles['pixel-svg']} 
                viewBox="0 0 32 32" 
                fill="none" 
                xmlns="http://www.w3.org/2000/svg"
            >
                {/* --- CAT EARS --- */}
                {/* Left Ear */}
                <g className={styles['left-ear']}>
                    {/* Outer Ear (Theme Color) */}
                    <rect x="6" y="1" width="2" height="1" className={styles['hair-theme']} />
                    <rect x="5" y="2" width="4" height="1" className={styles['hair-theme']} />
                    <rect x="4" y="3" width="6" height="1" className={styles['hair-theme']} />
                    <rect x="3" y="4" width="8" height="2" className={styles['hair-theme']} />
                    {/* Inner Ear (Pink Accent) */}
                    <rect x="5" y="3" width="4" height="2" fill="var(--avatar-ear-inner, #FF9EAD)" />
                </g>

                {/* Right Ear */}
                <g className={styles['right-ear']}>
                    {/* Outer Ear (Theme Color) */}
                    <rect x="24" y="1" width="2" height="1" className={styles['hair-theme']} />
                    <rect x="23" y="2" width="4" height="1" className={styles['hair-theme']} />
                    <rect x="22" y="3" width="6" height="1" className={styles['hair-theme']} />
                    <rect x="21" y="4" width="8" height="2" className={styles['hair-theme']} />
                    {/* Inner Ear (Pink Accent) */}
                    <rect x="23" y="3" width="4" height="2" fill="var(--avatar-ear-inner, #FF9EAD)" />
                </g>

                {/* --- HAIR (Back/Sides) --- */}
                <rect x="5" y="8" width="2" height="12" className={styles['hair-theme']} />
                <rect x="25" y="8" width="2" height="12" className={styles['hair-theme']} />
                <rect x="7" y="6" width="18" height="2" className={styles['hair-theme']} />

                {/* --- FACE SKIN --- */}
                <rect x="7" y="8" width="18" height="13" rx="1" fill="var(--avatar-skin-color, #FFEAE2)" />
                <rect x="14" y="21" width="4" height="2" fill="var(--avatar-skin-color, #FFEAE2)" />

                {/* --- HAIR BANGS (刘海) --- */}
                <rect x="7" y="8" width="18" height="3" className={styles['hair-theme']} />
                <rect x="7" y="11" width="2" height="2" className={styles['hair-theme']} />
                <rect x="15" y="11" width="2" height="1.5" className={styles['hair-theme']} />
                <rect x="23" y="11" width="2" height="2" className={styles['hair-theme']} />

                {/* --- BLUSH (脸上红晕) --- */}
                <rect x="8" y="16" width="2" height="1" className={styles['blush-pixel']} />
                <rect x="22" y="16" width="2" height="1" className={styles['blush-pixel']} />

                {/* --- EYES & EXPRESSIONS based on state --- */}
                {isDizzy ? (
                    /* Dizzy state: Crossed X X eyes with blushing cheeks */
                    <g className={styles['eyes-dizzy']}>
                        {/* Left X */}
                        <line x1="9" y1="13" x2="12" y2="16" stroke="var(--avatar-eye-color, #1E293B)" strokeWidth="1.5" strokeLinecap="square" />
                        <line x1="12" y1="13" x2="9" y2="16" stroke="var(--avatar-eye-color, #1E293B)" strokeWidth="1.5" strokeLinecap="square" />
                        
                        {/* Right X */}
                        <line x1="20" y1="13" x2="23" y2="16" stroke="var(--avatar-eye-color, #1E293B)" strokeWidth="1.5" strokeLinecap="square" />
                        <line x1="23" y1="13" x2="20" y2="16" stroke="var(--avatar-eye-color, #1E293B)" strokeWidth="1.5" strokeLinecap="square" />
                    </g>
                ) : isStreaming ? (
                    /* Thinking / Streaming state: happy closed eyes ^ ^ */
                    <g className={styles['eyes-thinking']}>
                        {/* Left ^ */}
                        <path d="M9 15 L10.5 13.5 L12 15" stroke="var(--avatar-eye-color, #1E293B)" strokeWidth="1.5" strokeLinecap="square" fill="none" />
                        {/* Right ^ */}
                        <path d="M20 15 L21.5 13.5 L23 15" stroke="var(--avatar-eye-color, #1E293B)" strokeWidth="1.5" strokeLinecap="square" fill="none" />
                    </g>
                ) : isUserTyping ? (
                    /* Typing / Listening state: Eager yellow starry eyes 🤩 */
                    <g className={styles['eyes-typing']}>
                        {/* Left Star */}
                        <polygon points="10.5,12 11.5,14 13.5,14.5 11.5,15 10.5,17 9.5,15 7.5,14.5 9.5,14" fill="#FBBF24" />
                        {/* Right Star */}
                        <polygon points="21.5,12 22.5,14 24.5,14.5 22.5,15 21.5,17 20.5,15 18.5,14.5 20.5,14" fill="#FBBF24" />
                    </g>
                ) : (
                    /* Idle state: Big anime blinking eyes with sparkling white reflections */
                    <g className={styles['eyes-idle']}>
                        {/* Left Eye */}
                        <rect x="9" y="13" width="3" height="4" className={styles['eye-left-base']} fill="var(--avatar-eye-color, #1E293B)" />
                        <rect x="9" y="13" width="1" height="1" className={styles['eye-sparkle']} fill="#FFFFFF" />
                        
                        {/* Right Eye */}
                        <rect x="20" y="13" width="3" height="4" className={styles['eye-right-base']} fill="var(--avatar-eye-color, #1E293B)" />
                        <rect x="20" y="13" width="1" height="1" className={styles['eye-sparkle']} fill="#FFFFFF" />
                    </g>
                )}

                {/* --- MOUTH --- */}
                {isDizzy ? (
                    /* Dizzy: funny open wavy mouth */
                    <path d="M14 18 Q16 20 18 18" stroke="var(--avatar-eye-color, #1E293B)" strokeWidth="1.5" fill="none" />
                ) : isStreaming ? (
                    /* Thinking: wavy talking line */
                    <rect x="14" y="18" width="4" height="2" className={styles['bot-mouth-thinking']} fill="var(--avatar-mouth-color, #E11D48)" />
                ) : isUserTyping ? (
                    /* Typing: excited open circular 'o' mouth */
                    <rect x="15" y="18" width="2" height="2.5" rx="1" fill="var(--avatar-mouth-color, #E11D48)" />
                ) : (
                    /* Idle: happy tiny smile */
                    <rect x="15" y="18" width="2" height="1" fill="var(--avatar-mouth-color, #E11D48)" />
                )}
            </svg>
        </div>
    );
};

export default PixelAvatar;
