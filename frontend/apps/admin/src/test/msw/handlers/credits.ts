import { http, HttpResponse } from 'msw';
import { API_URLS } from '../../../api/urls';
import { requireAuth } from '../utils';

let mockBalance = 500;
let isCheckedInToday = false;

export function resetCreditMocks() {
  mockBalance = 500;
  isCheckedInToday = false;
}

export const creditHandlers = [
  // 1. 获取积分信息
  http.get(API_URLS.CREDITS.ME, ({ request }) => {
    const auth = requireAuth(request);
    if (!auth.authorized) return auth.response;
    return HttpResponse.json({
      id: '88888888-8888-4888-8888-888888888888',
      user_id: '11111111-1111-4111-a111-111111111111',
      balance: mockBalance,
      is_checked_in_today: isCheckedInToday,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),

  // 2. 签到接口
  http.post(API_URLS.CREDITS.CHECKIN, ({ request }) => {
    const auth = requireAuth(request);
    if (!auth.authorized) return auth.response;
    if (isCheckedInToday) {
      return HttpResponse.json(
        { detail: 'ALREADY_CHECKED_IN' },
        { status: 400 }
      );
    }
    isCheckedInToday = true;
    mockBalance += 100;
    return HttpResponse.json({
      success: true,
      balance: mockBalance,
      amount_earned: 100,
      expires_at: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
    });
  }),

  // 3. 流水变动接口
  http.get(API_URLS.CREDITS.TRANSACTIONS, ({ request }) => {
    const auth = requireAuth(request);
    if (!auth.authorized) return auth.response;

    const url = new URL(request.url);
    const source = url.searchParams.get('source');

    let items = [
      {
        id: '22222222-2222-4222-a222-222222222222',
        account_id: '88888888-8888-4888-8888-888888888888',
        amount: 100,
        source: 'checkin',
        expires_at: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
        created_at: new Date().toISOString(),
      },
      {
        id: '33333333-3333-4333-a333-333333333333',
        account_id: '88888888-8888-4888-8888-888888888888',
        amount: -5,
        source: 'spend',
        expires_at: null,
        created_at: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
      }
    ];

    if (source) {
      items = items.filter(item => item.source === source);
    }

    return HttpResponse.json({
      items,
      total: items.length,
    });
  }),
];
