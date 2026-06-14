import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Spin, message as antdMessage } from 'antd';
import { ArrowLeft, Coins, CheckCircle2, Calendar, ClipboardList, LogIn } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { AppHttpError } from '../../lib/http/errors';
import {
  useMyCreditsQuery,
  useCreditTransactionsQuery,
  useDailyCheckinMutation
} from '../../query/hooks/credits';
import type { CreditTransaction } from '../../schemas/credit';
import styles from './CreditsPage.module.css';

const CreditsPage: React.FC = () => {
  const { isAuthenticated, setShowAuthModal } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();

  // Queries
  const { data: credits, isLoading: loadingCredits } = useMyCreditsQuery();
  const { data: checkinHistory } = useCreditTransactionsQuery({ source: 'checkin', limit: 100 });
  const { data: transactions, isLoading: loadingTransactions } = useCreditTransactionsQuery({ limit: 20 });

  // Mutation
  const checkinMutation = useDailyCheckinMutation();

  const handleCheckin = async () => {
    try {
      const response = await checkinMutation.mutateAsync();
      antdMessage.success(t('credits.success_earn', { amount: response.amount_earned }));
    } catch (err: unknown) {
      if (err instanceof AppHttpError) {
        if (err.code === 'validation' && String(err.details).includes('ALREADY_CHECKED_IN')) {
          antdMessage.warning(t('credits.checked_in_today'));
        }
        return;
      }
    }
  };

  // Generate Calendar days
  const [today, setToday] = React.useState(() => new Date());
  React.useEffect(() => {
    const ms = (() => {
      const now = new Date();
      const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
      return midnight.getTime() - now.getTime();
    })();
    const timer = setTimeout(() => setToday(new Date()), ms);
    return () => clearTimeout(timer);
  }, [today]);
  const currentYear = today.getFullYear();
  const currentMonth = today.getMonth();
  const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
  const firstDayIndex = new Date(currentYear, currentMonth, 1).getDay();

  // Map checked in days in local timezone
  const checkedDays = React.useMemo(() => {
    const days = new Set<number>();
    if (checkinHistory?.items) {
      checkinHistory.items.forEach((tx) => {
        const txDate = new Date(tx.created_at);
        if (txDate.getFullYear() === currentYear && txDate.getMonth() === currentMonth) {
          days.add(txDate.getDate());
        }
      });
    }
    return days;
  }, [checkinHistory, currentYear, currentMonth]);

  const calendarDays = React.useMemo(() => {
    const days: Array<{ dayNum: number | null; isToday: boolean; isChecked: boolean }> = [];
    for (let i = 0; i < firstDayIndex; i++) {
      days.push({ dayNum: null, isToday: false, isChecked: false });
    }
    for (let d = 1; d <= daysInMonth; d++) {
      const isToday = d === today.getDate();
      const isChecked = checkedDays.has(d);
      days.push({ dayNum: d, isToday, isChecked });
    }
    return days;
  }, [daysInMonth, firstDayIndex, checkedDays, today]);

  // Handle unauthorized state (Glassmorphism landing page)
  if (!isAuthenticated) {
    return (
      <div className={styles['credits-page']}>
        <div className={styles.container}>
          <div className={styles['back-header']}>
            <button className={styles['back-btn']} onClick={() => navigate('/')}>
              <ArrowLeft size={16} />
              {t('credits.back_home')}
            </button>
          </div>
          <div className={styles['guest-view']}>
            <div className={styles['guest-icon-wrapper']}>
              <Coins size={36} />
            </div>
            <div className={styles['guest-title']}>{t('credits.title')}</div>
            <div className={styles['guest-desc']}>{t('credits.guest_tip')}</div>
            <button className={styles['guest-login-btn']} onClick={() => setShowAuthModal(true)}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <LogIn size={18} />
                {t('credits.guest_btn')}
              </span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Format transaction type labels
  const getSourceLabel = (source: string) => {
    switch (source) {
      case 'checkin':
        return t('credits.source_checkin');
      case 'spend':
        return t('credits.source_spend');
      case 'expire':
        return t('credits.source_expire');
      case 'adjust':
        return t('credits.source_adjust');
      default:
        return source;
    }
  };

  const getSourceStyle = (source: string) => {
    switch (source) {
      case 'checkin':
        return styles.positive;
      default:
        return styles.negative;
    }
  };

  const formatExpiresAt = (tx: CreditTransaction) => {
    if (!tx.expires_at) return t('credits.no_expire');
    return new Date(tx.expires_at).toLocaleDateString();
  };

  const isCheckedInToday = credits?.is_checked_in_today ?? false;

  return (
    <div className={styles['credits-page']}>
      <div className={styles.container}>
        {/* Back navigation */}
        <div className={styles['back-header']}>
          <button className={styles['back-btn']} onClick={() => navigate('/')}>
            <ArrowLeft size={16} />
            {t('credits.back_home')}
          </button>
        </div>

        {/* Hero Card */}
        <div className={styles['hero-card']}>
          <div className={styles['balance-section']}>
            <div className={styles['balance-label']}>{t('credits.my_balance')}</div>
            {loadingCredits ? (
              <Spin size="small" />
            ) : (
              <div className={styles['balance-amount']}>
                {credits?.balance ?? 0}
                <span>Credits</span>
              </div>
            )}
          </div>

          <div className={styles['checkin-section']}>
            {isCheckedInToday ? (
              <div className={styles['checked-in-badge']}>
                <CheckCircle2 size={18} />
                {t('credits.checked_in_today')}
              </div>
            ) : (
              <button
                className={styles['checkin-btn']}
                disabled={checkinMutation.isPending}
                onClick={handleCheckin}
              >
                {checkinMutation.isPending ? (
                  <Spin size="small" />
                ) : (
                  <>
                    <Coins size={18} />
                    {t('credits.checkin_btn')}
                  </>
                )}
              </button>
            )}
            {checkinHistory?.items?.[0]?.expires_at && (
              <div className={styles['validity-text']}>
                {t('credits.expires_on', {
                  date: new Date(checkinHistory.items[0].expires_at).toLocaleDateString(),
                })}
              </div>
            )}
          </div>
        </div>

        {/* Contents Grid */}
        <div className={styles['content-grid']}>
          {/* Sign-in Calendar */}
          <div className={styles.card}>
            <div className={styles['card-title']}>
              <Calendar size={20} className={styles.icon} />
              {t('credits.calendar_title')}
            </div>
            <div className={styles['card-desc']}>{t('credits.calendar_tip')}</div>

            <div className={styles['calendar-grid']}>
              <div className={styles['calendar-header']}>
                {(t('credits.week_days', { returnObjects: true }) as string[]).map((day) => (
                  <span key={day}>{day}</span>
                ))}
              </div>

              {calendarDays.map((cell, index) => {
                if (cell.dayNum === null) {
                  return <div key={`empty-${index}`} className={`${styles['day-cell']} ${styles.empty}`} />;
                }
                return (
                  <div
                    key={`day-${cell.dayNum}`}
                    className={`${styles['day-cell']} ${cell.isChecked ? styles.checked : ''} ${
                      cell.isToday ? styles.today : ''
                    }`}
                  >
                    {cell.dayNum}
                    {cell.isChecked && <div className={styles['checkin-dot']} />}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Transactions Log */}
          <div className={styles.card}>
            <div className={styles['card-title']}>
              <ClipboardList size={20} className={styles.icon} />
              {t('credits.history_title')}
            </div>
            <div className={styles['card-desc']}>{t('credits.history_desc')}</div>

            <div className={styles['transactions-list']}>
              {loadingTransactions ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '40px 0' }}>
                  <Spin />
                </div>
              ) : !transactions?.items || transactions.items.length === 0 ? (
                <div className={styles['empty-state']}>
                  <Coins size={32} style={{ opacity: 0.4 }} />
                  <div>{t('credits.history_empty')}</div>
                </div>
              ) : (
                transactions.items.map((tx) => (
                  <div key={tx.id} className={styles['tx-item']}>
                    <div className={styles['tx-left']}>
                      <div className={styles['tx-title']}>{getSourceLabel(tx.source)}</div>
                      <div className={styles['tx-date']}>
                        {new Date(tx.created_at).toLocaleString()}
                      </div>
                      {tx.source === 'checkin' && (
                        <div className={styles['tx-expire']}>
                          {t('credits.column_expire')}: {formatExpiresAt(tx)}
                        </div>
                      )}
                    </div>
                    <div className={`${styles['tx-amount']} ${getSourceStyle(tx.source)}`}>
                      {tx.amount > 0 ? `+${tx.amount}` : tx.amount}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CreditsPage;
