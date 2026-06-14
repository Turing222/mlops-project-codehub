import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom';
import { Form, Input, Button, message as antdMessage } from 'antd';
import { User, Settings, X, Sun, Moon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/useAuth';
import { useUpdateProfileMutation } from '../../query/hooks/auth';
import { useThemeStore } from '../../stores/theme-store';
import { changeAppLanguage } from '../../lib/i18n';
import styles from './UserProfileModal.module.css';

interface UserProfileModalProps {
    isOpen: boolean;
    onClose: () => void;
}

type TabType = 'profile' | 'preferences';

const BRAND_PRESETS = [
    { key: 'blue', value: '#1677ff' },
    { key: 'indigo', value: '#4f46e5' },
    { key: 'purple', value: '#722ed1' },
    { key: 'teal', value: '#0d9488' },
    { key: 'orange', value: '#ea580c' },
];

const UserProfileModal: React.FC<UserProfileModalProps> = ({ isOpen, onClose }) => {
    const { t, i18n } = useTranslation();
    const { user, refreshUser } = useAuth();
    const [activeTab, setActiveTab] = useState<TabType>('profile');

    // Theme & accent store integration
    const { theme, brandColor, setTheme, setBrandColor } = useThemeStore();

    // Mutation for profile
    const updateProfileMutation = useUpdateProfileMutation();
    const [profileForm] = Form.useForm();

    // Reset form values when modal opens or user data changes
    useEffect(() => {
        if (isOpen && user) {
            profileForm.setFieldsValue({
                username: user.username,
                email: user.email || '',
                phone: user.phone || '',
            });
        }
    }, [isOpen, user, profileForm]);

    if (!isOpen) return null;

    // Save basic profile
    const handleProfileSave = async (values: { username: string; email: string; phone: string }) => {
        try {
            await updateProfileMutation.mutateAsync({
                username: values.username,
                email: values.email || undefined,
                phone: values.phone || undefined,
            });
            await refreshUser();
            antdMessage.success(t('auth.profile_update_success', '个人信息更新成功'));
            onClose();
        } catch (err: unknown) {
            const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
                || (err instanceof Error ? err.message : undefined);
            antdMessage.error(detail || t('auth.profile_update_error', '更新个人信息失败'));
        }
    };

    // Trigger language toggle
    const handleLanguageChange = (lng: string) => {
        void changeAppLanguage(lng);
        antdMessage.success(lng === 'zh-CN' ? '界面语言已切换为中文' : 'Language set to English');
    };

    const sidebarItems = [
        { key: 'profile', label: t('chat.profile_modal.tab_profile', '个人资料'), icon: <User size={16} /> },
        { key: 'preferences', label: t('chat.profile_modal.tab_preferences', '偏好设置'), icon: <Settings size={16} /> },
    ];

    return ReactDOM.createPortal(
        <div className={styles['modal-overlay']} onClick={onClose}>
            <div className={styles['modal-container']} onClick={(e) => e.stopPropagation()}>
                {/* Close Button */}
                <button className={styles['close-btn']} onClick={onClose}>
                    <X size={18} />
                </button>

                {/* Sidebar Navigation */}
                <div className={styles['modal-sidebar']}>
                    <div className={styles['sidebar-title']}>
                        {t('chat.profile_modal.title', '账号设置')}
                    </div>
                    <div className={styles['sidebar-menu']}>
                        {sidebarItems.map((item) => (
                            <button
                                key={item.key}
                                className={`${styles['menu-item']} ${activeTab === item.key ? styles['active'] : ''}`}
                                onClick={() => setActiveTab(item.key as TabType)}
                            >
                                {item.icon}
                                <span>{item.label}</span>
                            </button>
                        ))}
                    </div>
                </div>

                {/* Main Content Area */}
                <div className={styles['modal-main']}>
                    {activeTab === 'profile' && (
                        <>
                            <div className={styles['main-header']}>
                                <h2>{t('chat.profile_modal.tab_profile', '个人资料')}</h2>
                                <p>{t('chat.profile_modal.profile_desc', '更新您的基本账号公开及联系信息')}</p>
                            </div>

                            <Form
                                form={profileForm}
                                layout="vertical"
                                onFinish={handleProfileSave}
                                className={styles['profile-form']}
                            >
                                <Form.Item
                                    name="username"
                                    label={t('auth.username', '用户名')}
                                    rules={[
                                        { required: true, message: t('auth.validation.username_required', '请输入用户名') },
                                        { min: 3, message: t('auth.validation.username_min', '用户名最少需要3个字符') },
                                        { pattern: /^[a-zA-Z0-9_]+$/, message: t('auth.validation.username_pattern', '只能包含字母、数字和下划线') }
                                    ]}
                                >
                                    <Input placeholder={t('auth.username_placeholder', '请输入用户名')} />
                                </Form.Item>

                                <Form.Item
                                    name="email"
                                    label={t('auth.email', '邮箱')}
                                    rules={[
                                        { type: 'email', message: t('auth.validation.email_invalid', '请输入有效的邮箱') }
                                    ]}
                                >
                                    <Input placeholder={t('auth.email_placeholder', '请输入邮箱')} />
                                </Form.Item>

                                <Form.Item
                                    name="phone"
                                    label={t('auth.phone', '手机号')}
                                    rules={[
                                        { pattern: /^\+?\d{7,15}$/, message: t('auth.validation.phone_invalid', '请输入有效的手机号') }
                                    ]}
                                >
                                    <Input placeholder={t('auth.phone_placeholder', '请输入手机号')} />
                                </Form.Item>

                                <div className={styles['form-actions']}>
                                    <Button onClick={onClose} className={styles['cancel-btn']}>
                                        {t('common.cancel', '取消')}
                                    </Button>
                                    <Button
                                        type="primary"
                                        htmlType="submit"
                                        loading={updateProfileMutation.isPending}
                                        className={styles['submit-btn']}
                                    >
                                        {t('common.save', '保存修改')}
                                    </Button>
                                </div>
                            </Form>
                        </>
                    )}

                    {activeTab === 'preferences' && (
                        <>
                            <div className={styles['main-header']}>
                                <h2>{t('chat.profile_modal.tab_preferences', '偏好设置')}</h2>
                                <p>{t('chat.profile_modal.preferences_desc', '管理您的视觉主题、全局语言及个性化配置')}</p>
                            </div>

                            <div className={styles['preferences-layout']}>
                                {/* Theme preference */}
                                <div className={styles['preference-item']}>
                                    <div className={styles['pref-info']}>
                                        <div className={styles['pref-label']}>{t('sidebar.theme', '外观主题')}</div>
                                        <div className={styles['pref-desc']}>选择您偏好的系统光影外观样式</div>
                                    </div>
                                    <div className={styles['pref-control-row']}>
                                        <button
                                            className={`${styles['control-btn']} ${theme === 'light' ? styles['active'] : ''}`}
                                            onClick={() => setTheme('light')}
                                        >
                                            <Sun size={14} />
                                            <span>{t('sidebar.light_mode', '浅色模式')}</span>
                                        </button>
                                        <button
                                            className={`${styles['control-btn']} ${theme === 'dark' ? styles['active'] : ''}`}
                                            onClick={() => setTheme('dark')}
                                        >
                                            <Moon size={14} />
                                            <span>{t('sidebar.dark_mode', '深色模式')}</span>
                                        </button>
                                    </div>
                                </div>

                                {/* Language Preference */}
                                <div className={styles['preference-item']}>
                                    <div className={styles['pref-info']}>
                                        <div className={styles['pref-label']}>{t('sidebar.language', '界面语言')}</div>
                                        <div className={styles['pref-desc']}>更改整个操作面板的文字呈现语言</div>
                                    </div>
                                    <div className={styles['pref-control-row']}>
                                        <button
                                            className={`${styles['control-btn']} ${i18n.language === 'zh-CN' ? styles['active'] : ''}`}
                                            onClick={() => handleLanguageChange('zh-CN')}
                                        >
                                            中文 (简体)
                                        </button>
                                        <button
                                            className={`${styles['control-btn']} ${i18n.language === 'en-US' ? styles['active'] : ''}`}
                                            onClick={() => handleLanguageChange('en-US')}
                                        >
                                            English
                                        </button>
                                    </div>
                                </div>

                                {/* Brand Preset Accent Colors */}
                                <div className={styles['preference-item']}>
                                    <div className={styles['pref-info']}>
                                        <div className={styles['pref-label']}>{t('sidebar.accent_color', '系统主题色')}</div>
                                        <div className={styles['pref-desc']}>挑选亮显文字和激活状态图标的色系</div>
                                    </div>
                                    <div className={styles['color-row']}>
                                        {BRAND_PRESETS.map((color) => (
                                            <button
                                                key={color.value}
                                                className={`${styles['color-preset-circle']} ${brandColor === color.value ? styles['color-preset-circle-active'] : ''}`}
                                                style={{ backgroundColor: color.value }}
                                                title={t(`sidebar.brand_colors.${color.key}`)}
                                                onClick={() => {
                                                    setBrandColor(color.value);
                                                    antdMessage.success(`系统主题色已应用为 ${t(`sidebar.brand_colors.${color.key}`)}`);
                                                }}
                                            />
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>,
        document.body
    );
};

export default UserProfileModal;
