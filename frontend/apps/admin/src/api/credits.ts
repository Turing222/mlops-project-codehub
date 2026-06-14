import request from '../lib/http/client';
import { parseWithSchema } from '../schemas/parse';
import { API_URLS } from './urls';
import {
  creditAccountResponseSchema,
  checkinResponseSchema,
  creditTransactionsListResponseSchema,
  type CreditAccount,
  type CheckinResponse,
  type CreditTransactionsList
} from '../schemas/credit';

export const getMyCreditsAPI = (): Promise<CreditAccount> => {
  return request
    .get<unknown, unknown>(API_URLS.CREDITS.ME)
    .then((response) =>
      parseWithSchema(
        creditAccountResponseSchema,
        response,
        '获取积分账户响应格式无效'
      )
    );
};

export const dailyCheckinAPI = (): Promise<CheckinResponse> => {
  return request
    .post<unknown, unknown>(API_URLS.CREDITS.CHECKIN)
    .then((response) =>
      parseWithSchema(
        checkinResponseSchema,
        response,
        '每日签到响应格式无效'
      )
    );
};

export const listMyTransactionsAPI = (params?: {
  source?: string;
  skip?: number;
  limit?: number;
}): Promise<CreditTransactionsList> => {
  return request
    .get<unknown, unknown>(API_URLS.CREDITS.TRANSACTIONS, { params })
    .then((response) =>
      parseWithSchema(
        creditTransactionsListResponseSchema,
        response,
        '获取变动流水列表响应格式无效'
      )
    );
};
